#!/usr/bin/env python3
"""Stage, inspect, install, or explicitly recover the DSPACE producer."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ASSETS = {
    "usr/local/libexec/sugarkube-dspace-chat-synthetic": "scripts/dspace-chat-synthetic",
    "usr/local/libexec/sugarkube-dspace-chat-synthetic.py": "scripts/dspace_chat_synthetic.py",
    "etc/sugarkube/dspace-chat-synthetic.json": "config/dspace-chat-synthetic.json",
    "etc/systemd/system/dspace-chat-synthetic.service": (
        "scripts/systemd/dspace-chat-synthetic.service"
    ),
    "etc/systemd/system/dspace-chat-synthetic.timer": "scripts/systemd/dspace-chat-synthetic.timer",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(repo: Path, root: Path) -> dict:
    hashes = {}
    for target, source in ASSETS.items():
        src = repo / source
        if not src.is_file():
            raise ValueError(f"missing repository asset: {source}")
        dst = root / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        os.chmod(dst, 0o755 if target.startswith("usr/") else 0o644)
        hashes[target] = digest(dst)
    config = json.loads((root / "etc/sugarkube/dspace-chat-synthetic.json").read_text())
    if config["wrapper_path"] != "/usr/local/libexec/sugarkube-dspace-chat-synthetic":
        raise ValueError("wrapper target mismatch")
    if (
        "Persistent=true"
        not in (root / "etc/systemd/system/dspace-chat-synthetic.timer").read_text()
    ):
        raise ValueError("timer is not persistent")
    return {"schema_version": 1, "revision": config["runner_revision"], "files": hashes}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "command", nargs="?", choices=("dry-run", "apply", "status", "rollback"), default="dry-run"
    )
    p.add_argument("--root", type=Path, default=Path("/"))
    p.add_argument("--repo", type=Path, default=REPO)
    p.add_argument("--revision")
    a = p.parse_args()
    installed = a.root / "var/lib/sugarkube/dspace-chat-installer"
    current = installed / "current.json"
    retained = installed / "retained"
    if a.command == "status":
        value = json.loads(current.read_text()) if current.exists() else {"installed": False}
        value["timer_enabled"] = (
            subprocess.run(
                ["systemctl", "is-enabled", "dspace-chat-synthetic.timer"], capture_output=True
            ).returncode
            == 0
            if a.root == Path("/")
            else None
        )
        print(json.dumps(value, sort_keys=True))
        return 0
    if a.command == "rollback":
        if not a.revision or not (retained / f"{a.revision}.json").is_file():
            p.error("rollback requires an exact validated retained revision")
        manifest = json.loads((retained / f"{a.revision}.json").read_text())
        for target, expected in manifest["files"].items():
            candidate = retained / a.revision / target
            if not candidate.is_file() or digest(candidate) != expected:
                p.error("retained revision validation failed")
            dst = a.root / target
            tmp = dst.with_name(f".{dst.name}.rollback")
            shutil.copy2(candidate, tmp)
            os.replace(tmp, dst)
        current.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        return 0
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary)
        manifest = stage(a.repo, staged)
        print(json.dumps(manifest, sort_keys=True))
        if a.command == "dry-run":
            return 0
        installed.mkdir(parents=True, exist_ok=True)
        retained.mkdir(exist_ok=True)
        if current.exists():
            old = json.loads(current.read_text())
            oldrev = old["revision"]
            oldroot = retained / oldrev
            if not oldroot.exists():
                for target in old["files"]:
                    dst = oldroot / target
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(a.root / target, dst)
                (retained / f"{oldrev}.json").write_text(json.dumps(old, sort_keys=True) + "\n")
        for target in ASSETS:
            dst = a.root / target
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.new")
            shutil.copy2(staged / target, tmp)
            os.replace(tmp, dst)
        tmp = current.with_suffix(".new")
        tmp.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        os.replace(tmp, current)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
