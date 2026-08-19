#!/usr/bin/env python3
"""Build an independent, immutable DSPACE smoke-runner snapshot from local source."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class MaterializeError(RuntimeError):
    pass


def run(argv: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise MaterializeError("runner construction command failed")
    return completed.stdout.strip()


def materialize(
    source: Path, revision: str, destination: Path, expected_origin: str, pnpm: str
) -> Path:
    source = source.resolve()
    if not (source / ".git").exists() or run(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"]
    ) != str(source):
        raise MaterializeError("source must be an explicitly identified repository root")
    origin = run(["git", "-C", str(source), "remote", "get-url", "origin"])
    if origin.rstrip("/").removesuffix(".git") != expected_origin.rstrip("/").removesuffix(".git"):
        raise MaterializeError("source repository identity mismatch")
    if run(["git", "-C", str(source), "rev-parse", "HEAD"]) != revision:
        raise MaterializeError("source HEAD is not the exact requested commit")
    run(["git", "-C", str(source), "cat-file", "-e", f"{revision}^{{commit}}"])
    if run(["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=no"]):
        raise MaterializeError("source tracked/index state is dirty")
    if (source / ".git/objects/info/alternates").exists():
        raise MaterializeError("source depends on an external object store")
    if not (source / "pnpm-lock.yaml").is_file() or not (source / "pnpm-workspace.yaml").is_file():
        raise MaterializeError("exact pnpm workspace inputs are missing")
    if destination.exists():
        raise MaterializeError("destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=destination.parent))
    try:
        # A local clone with --no-local copies every reachable object and creates no alternates.
        run(
            [
                "git",
                "clone",
                "--no-local",
                "--no-hardlinks",
                "--no-checkout",
                str(source),
                str(staging),
            ]
        )
        run(["git", "-C", str(staging), "checkout", "--detach", revision])
        run(["git", "-C", str(staging), "reflog", "expire", "--expire=now", "--all"])
        run(["git", "-C", str(staging), "gc", "--prune=now"])
        if (staging / ".git/objects/info/alternates").exists():
            raise MaterializeError("snapshot unexpectedly contains alternates")
        run(["git", "-C", str(staging), "fsck", "--full", "--no-dangling"])
        env = os.environ.copy()
        env["CI"] = "1"
        completed = subprocess.run(
            [pnpm, "install", "--frozen-lockfile", "--offline"],
            cwd=staging,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode:
            raise MaterializeError("offline frozen pnpm installation failed")
        critical = [
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "package.json",
            "apps/web/package.json",
            "apps/web/tests/remote-chat-smoke.spec.ts",
        ]
        for relative in critical:
            if not (staging / relative).is_file():
                raise MaterializeError(f"critical runner file missing: {relative}")
        store, cli = (
            staging / "node_modules/.pnpm",
            staging / "apps/web/node_modules/.bin/playwright",
        )
        if not store.is_dir() or not any(store.iterdir()):
            raise MaterializeError("root pnpm store missing")
        if any(
            path.is_symlink() and not path.exists()
            for path in (staging / "apps/web/node_modules").rglob("*")
        ):
            raise MaterializeError("broken frontend dependency link")
        if not cli.is_file() or not os.access(cli, os.X_OK):
            raise MaterializeError("Playwright CLI/shim missing")
        run([str(cli), "--version"], cwd=staging)
        run(["node", "-e", "require.resolve('@playwright/test')"], cwd=staging / "apps/web")
        files = {
            relative: hashlib.sha256((staging / relative).read_bytes()).hexdigest()
            for relative in critical
        }
        (staging / "sugarkube-runner-manifest.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runnerRevision": revision,
                    "sourceOrigin": expected_origin,
                    "files": files,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--expected-origin", default="https://github.com/democratizedspace/dspace")
    parser.add_argument("--pnpm", default="pnpm")
    args = parser.parse_args()
    try:
        materialize(args.source, args.revision, args.destination, args.expected_origin, args.pnpm)
    except (MaterializeError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
