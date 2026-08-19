#!/usr/bin/env python3
"""Render, verify, install, status-check, or explicitly roll back the producer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "usr/local/libexec/sugarkube-dspace-chat-synthetic": (
        "scripts/dspace_chat_synthetic_wrapper.sh"
    ),
    "usr/local/libexec/sugarkube-dspace-chat-synthetic-runtime": (
        "scripts/dspace_chat_synthetic_runtime.py"
    ),
    "usr/local/libexec/sugarkube-dspace-chat-synthetic-metrics": (
        "scripts/dspace_chat_synthetic_metrics.py"
    ),
    "etc/sugarkube/dspace-chat-synthetic.json": "config/dspace-chat-synthetic.json",
    "etc/systemd/system/dspace-chat-synthetic.service": (
        "scripts/systemd/dspace-chat-synthetic.service"
    ),
    "etc/systemd/system/dspace-chat-synthetic.timer": "scripts/systemd/dspace-chat-synthetic.timer",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(destination: Path) -> dict[str, str]:
    hashes = {}
    for target, source in ASSETS.items():
        src = ROOT / source
        out = destination / target
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        out.chmod(0o755 if "/libexec/" in target else 0o644)
        hashes[target] = sha(out)
    (destination / "manifest.json").write_text(json.dumps(hashes, sort_keys=True, indent=2) + "\n")
    return hashes


def validate(tree: Path) -> dict[str, str]:
    manifest = json.loads((tree / "manifest.json").read_text())
    if set(manifest) != set(ASSETS):
        raise ValueError("asset manifest is incomplete")
    for target, expected in manifest.items():
        path = tree / target
        if not path.is_file() or sha(path) != expected:
            raise ValueError("staged asset hash mismatch")
    config = json.loads((tree / "etc/sugarkube/dspace-chat-synthetic.json").read_text())
    if config.get("runnerRevision") != "97ab09f13fb098de928a878bf1fe9b8d13032cb5":
        raise ValueError("unapproved runner revision")
    if (
        "Persistent=true"
        not in (tree / "etc/systemd/system/dspace-chat-synthetic.timer").read_text()
    ):
        raise ValueError("timer is not persistent")
    return manifest


def status(root: Path) -> int:
    for target in ASSETS:
        path = root / target
        print(f"{target} sha256={sha(path) if path.is_file() else 'missing'}")
    config = root / "etc/sugarkube/dspace-chat-synthetic.json"
    if config.is_file():
        value = json.loads(config.read_text())
        runner = value.get("runnerRevision", "invalid")
        source = value.get("dspaceSourceRevision", "invalid")
        print(f"runner={runner} source={source}")
    # Read-only activation inspection; absence of systemctl is reported, never repaired.
    for unit in ("dspace-chat-synthetic.service", "dspace-chat-synthetic.timer"):
        result = (
            subprocess.run(
                ["systemctl", "is-active", unit], capture_output=True, text=True, check=False
            )
            if shutil.which("systemctl")
            else None
        )
        print(f"{unit} active={result.stdout.strip() if result else 'unknown'}")
    return 0


def activate(retained: Path, root: Path, revision: str) -> None:
    validate(retained)
    current = retained.parent / "current"
    temporary = retained.parent / ".current.new"
    temporary.symlink_to(revision)
    os.replace(temporary, current)
    for target in ASSETS:
        destination = root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{destination.name}.new")
        shutil.copy2(retained / target, temp)
        os.replace(temp, destination)


def install(staged: Path, root: Path, revision: str) -> None:
    validate(staged)
    retained = root / "var/lib/sugarkube/dspace-chat-installations" / revision
    if retained.exists():
        raise ValueError("exact retained revision already exists")
    retained.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staged, retained)
    activate(retained, root, revision)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        nargs="?",
        choices=("dry-run", "apply", "status", "rollback"),
        default="dry-run",
    )
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--revision", default="97ab09f13fb098de928a878bf1fe9b8d13032cb5")
    args = parser.parse_args()
    if args.operation == "status":
        return status(args.root)
    if args.operation == "rollback":
        retained = args.root / "var/lib/sugarkube/dspace-chat-installations" / args.revision
        activate(retained, args.root, args.revision)
        return 0
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary)
        render(staged)
        validate(staged)
        if args.operation == "apply":
            install(staged, args.root, args.revision)
        else:
            print("validation=passed mutation=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
