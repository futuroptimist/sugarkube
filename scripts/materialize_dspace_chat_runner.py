#!/usr/bin/env python3
"""Construct and attest an independent immutable DSPACE smoke runner."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

CRITICAL = (
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "scripts/run-remote-chat-smoke.mjs",
    "tests/remote-chat-smoke.spec.ts",
)


def run(*args, cwd=None, env=None):
    return subprocess.run(
        args, cwd=cwd, env=env, check=True, text=True, capture_output=True
    ).stdout.strip()


def validate_source(source: Path, revision: str, repository: str) -> None:
    if len(revision) != 40 or run("git", "-C", str(source), "cat-file", "-t", revision) != "commit":
        raise ValueError("exact commit object is missing")
    if run("git", "-C", str(source), "rev-parse", "HEAD") != revision:
        raise ValueError("source HEAD is not the requested exact commit")
    if run("git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("source tracked/index state is dirty")
    remotes = run("git", "-C", str(source), "remote", "get-url", "origin")
    if remotes.rstrip("/").removesuffix(".git") != repository.rstrip("/").removesuffix(".git"):
        raise ValueError("source repository identity mismatch")


def validate(snapshot: Path, revision: str) -> dict:
    if (
        not (snapshot / ".git/objects").is_dir()
        or (snapshot / ".git/objects/info/alternates").exists()
    ):
        raise ValueError("incomplete or externally dependent Git metadata")
    if run("git", "-C", str(snapshot), "rev-parse", "HEAD") != revision or run(
        "git", "-C", str(snapshot), "fsck", "--full"
    ):
        raise ValueError("snapshot Git state mismatch")
    if run("git", "-C", str(snapshot), "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("snapshot tracked/index state is dirty")
    if not (snapshot / "node_modules/.pnpm").is_dir():
        raise ValueError("root pnpm store is missing")
    cli = snapshot / "node_modules/.bin/playwright"
    if (
        not cli.exists()
        or not os.access(cli, os.X_OK)
        or (cli.is_symlink() and not cli.resolve().exists())
    ):
        raise ValueError("Playwright CLI/shim is invalid")
    run("node", "-e", "require.resolve('@playwright/test')", cwd=snapshot)
    files = {}
    for name in CRITICAL:
        path = snapshot / name
        if not path.is_file():
            raise ValueError(f"critical file is missing: {name}")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (snapshot / "apps/frontend/node_modules").glob("*"):
        if path.is_symlink() and not path.resolve().exists():
            raise ValueError("broken frontend dependency symlink")
    return {"schema_version": 1, "revision": revision, "files": files}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--revision", required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--pnpm", default="pnpm")
    a = p.parse_args()
    validate_source(a.source.resolve(), a.revision, a.repository)
    if a.output.exists():
        p.error("output already exists")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.output.parent) as temporary:
        stage = Path(temporary) / a.revision
        # --no-local forces copied objects and prevents hardlinks/alternates.
        run("git", "clone", "--no-local", "--no-checkout", str(a.source.resolve()), str(stage))
        run("git", "checkout", "--detach", a.revision, cwd=stage)
        env = {**os.environ, "CI": "true"}
        run(a.pnpm, "install", "--frozen-lockfile", cwd=stage, env=env)
        manifest = validate(stage, a.revision)
        (stage / "sugarkube-runner-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        os.replace(stage, a.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
