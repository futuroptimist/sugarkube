#!/usr/bin/env python3
"""Stage, inspect, install, or explicitly roll back the synthetic producer."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dspace_chat_synthetic import load_config, verify_runner  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "wrapper": ROOT / "scripts/dspace_chat_synthetic",
    "producer": ROOT / "scripts/dspace_chat_synthetic.py",
    "config": ROOT / "config/dspace-chat-synthetic/staging.json",
    "service": ROOT / "scripts/systemd/sugarkube-dspace-chat-synthetic.service",
    "timer": ROOT / "scripts/systemd/sugarkube-dspace-chat-synthetic.timer",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def targets(root: Path) -> dict[str, Path]:
    return {
        "wrapper": root / "usr/local/libexec/sugarkube-dspace-chat-synthetic",
        "producer": root / "usr/local/libexec/sugarkube-dspace-chat-synthetic.py",
        "config": root / "etc/sugarkube/dspace-chat-synthetic.json",
        "service": root / "etc/systemd/system/sugarkube-dspace-chat-synthetic.service",
        "timer": root / "etc/systemd/system/sugarkube-dspace-chat-synthetic.timer",
    }


def validate_assets() -> dict:
    config = load_config(ASSETS["config"])
    for asset in ASSETS.values():
        if not asset.is_file() or asset.is_symlink():
            raise ValueError("repository asset missing or linked")
    if "Persistent=true" not in ASSETS["timer"].read_text() or any(
        word in ASSETS["service"].read_text() + ASSETS["timer"].read_text()
        for word in ("systemctl start", "systemctl enable")
    ):
        raise ValueError("unit activation contract invalid")
    return config


def status(root: Path) -> None:
    config = validate_assets()
    installed = targets(root)
    print(
        f"runnerRevision={config['runnerRevision']} "
        f"dspaceVersion={config['dspaceVersion']} "
        f"sourceRevision={config['dspaceSourceRevision']}"
    )
    for name, source in ASSETS.items():
        target = installed[name]
        print(
            f"{name} repositorySha256={digest(source)} "
            f"installedSha256={digest(target) if target.is_file() else 'missing'}"
        )
    wants = root / "etc/systemd/system/timers.target.wants/sugarkube-dspace-chat-synthetic.timer"
    print(f"timerActivation={'present' if wants.exists() else 'absent'}")


def install(root: Path, runner: Path, apply: bool) -> None:
    config = validate_assets()
    if runner.resolve() != (
        Path(config["runnerRoot"]) / config["runnerRevision"]
    ).resolve() and root == Path("/"):
        raise ValueError("runner target coordinate mismatch")
    # Validate before touching an installed target. Test roots may use rendered configuration.
    if root == Path("/"):
        verify_runner(config)
    stage = Path(tempfile.mkdtemp(prefix="dspace-synthetic-stage."))
    try:
        for name, source in ASSETS.items():
            shutil.copy2(source, stage / name)
        if not apply:
            print("validated dry-run; no files or units changed")
            return
        installed = targets(root)
        retention = (
            root / "var/lib/sugarkube/dspace-chat-synthetic/retained" / config["runnerRevision"]
        )
        retention.mkdir(parents=True, exist_ok=True)
        for name, target in installed.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.copy2(target, retention / name)
            temporary = target.with_name(f".{target.name}.new")
            shutil.copy2(stage / name, temporary)
            os.chmod(temporary, 0o755 if name in {"wrapper", "producer"} else 0o644)
            os.replace(temporary, target)
        print("installed files only; no service or timer activation performed")
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def rollback(root: Path, revision: str, apply: bool) -> None:
    if not revision or any(c not in "0123456789abcdef" for c in revision) or len(revision) != 40:
        raise ValueError("rollback requires an exact revision")
    retained = root / "var/lib/sugarkube/dspace-chat-synthetic/retained" / revision
    installed = targets(root)
    if not retained.is_dir() or any(not (retained / name).is_file() for name in installed):
        raise ValueError("exact validated retained revision is unavailable")
    load_config(retained / "config")
    if not apply:
        print("validated rollback dry-run; no files or units changed")
        return
    for name, target in installed.items():
        temporary = target.with_name(f".{target.name}.rollback")
        shutil.copy2(retained / name, temporary)
        os.replace(temporary, target)
    print("rolled back files only; no service or timer activation performed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("validate", "install", "status", "rollback"),
        default="validate",
        nargs="?",
    )
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "status":
            status(args.root)
        elif args.action == "rollback":
            rollback(args.root, args.revision or "", args.apply)
        else:
            install(
                args.root,
                args.runner or Path("/nonexistent"),
                args.apply if args.action == "install" else False,
            )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
