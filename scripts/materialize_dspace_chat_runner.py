#!/usr/bin/env python3
"""Create a self-contained, immutable DSPACE smoke-runner snapshot from a local repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CRITICAL = (
    "scripts/run-remote-chat-smoke.mjs",
    "tests/remote-chat-smoke.spec.ts",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
)


def command(*argv: str, cwd: Path | None = None) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(source: Path, revision: str, identity: str) -> None:
    if not (source / ".git").exists():
        raise ValueError("complete Git metadata is required")
    command("git", "-C", str(source), "cat-file", "-e", f"{revision}^{{commit}}")
    if command("git", "-C", str(source), "rev-parse", "HEAD") != revision:
        raise ValueError("source HEAD does not equal the exact revision")
    if command("git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("source index or tracked worktree is dirty")
    origins = command("git", "-C", str(source), "remote", "get-url", "--all", "origin").splitlines()
    if identity not in origins:
        raise ValueError("repository identity mismatch")


def validate(snapshot: Path, revision: str) -> None:
    if command("git", "-C", str(snapshot), "rev-parse", "HEAD") != revision:
        raise ValueError("snapshot HEAD mismatch")
    command("git", "-C", str(snapshot), "fsck", "--full", "--no-dangling")
    if (snapshot / ".git/objects/info/alternates").exists():
        raise ValueError("snapshot depends on an external object store")
    if not (snapshot / "node_modules/.pnpm").is_dir():
        raise ValueError("root pnpm store missing")
    cli = snapshot / "node_modules/.bin/playwright"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ValueError("Playwright CLI/shim missing or invalid")
    subprocess.run(
        [str(cli), "--version"], cwd=snapshot, check=True, capture_output=True, timeout=15
    )
    command("node", "-e", "require.resolve('@playwright/test')", cwd=snapshot)
    for link in (snapshot / "frontend/node_modules").rglob("*"):
        if link.is_symlink() and not link.exists():
            raise ValueError("broken frontend dependency link")


def materialize(source: Path, revision: str, identity: str, output: Path, pnpm: str) -> None:
    verify_source(source, revision, identity)
    if output.exists():
        raise ValueError("output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=output.parent))
    try:
        # A normal local clone copies reachable objects. No hardlinks plus a repack remove source
        # ties.
        command(
            "git", "clone", "--local", "--no-hardlinks", "--no-checkout", str(source), str(staging)
        )
        command("git", "checkout", "--detach", revision, cwd=staging)
        command("git", "repack", "-a", "-d", cwd=staging)
        subprocess.run([pnpm, "install", "--frozen-lockfile", "--offline"], cwd=staging, check=True)
        validate(staging, revision)
        files = {}
        for relative in CRITICAL:
            path = staging / relative
            if not path.is_file():
                raise ValueError(f"critical runner file missing: {relative}")
            files[relative] = digest(path)
        manifest = {
            "schemaVersion": 1,
            "runnerRevision": revision,
            "repositoryIdentity": identity,
            "files": files,
        }
        (staging / "sugarkube-runner-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--repository-identity", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pnpm", default="pnpm")
    args = parser.parse_args()
    try:
        materialize(
            args.source.resolve(),
            args.revision,
            args.repository_identity,
            args.output.resolve(),
            args.pnpm,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
