#!/usr/bin/env python3
"""Render, verify, install, status-check, or explicitly roll back the producer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
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
REVISION = re.compile(r"[0-9a-f]{40}")
ASSET_REVISION = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
CRITICAL = (
    "scripts/run-remote-chat-smoke.mjs",
    "scripts/remote-chat-smoke-completion.mjs",
    "frontend/e2e/remote-chat-smoke.spec.ts",
    "package.json",
    "frontend/package.json",
    "pnpm-workspace.yaml",
    "pnpm-lock.yaml",
)


def runtime_module():
    """Load the runtime's canonical snapshot validator without path assumptions."""
    path = ROOT / "scripts/dspace_chat_synthetic_runtime.py"
    spec = importlib.util.spec_from_file_location("dspace_chat_synthetic_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("runtime validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(*argv: str, cwd: Path | None = None) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def verify_source(source: Path, revision: str, identity: str) -> None:
    if not REVISION.fullmatch(revision) or not (source / ".git").is_dir():
        raise ValueError("complete Git metadata and an exact commit are required")
    if command("git", "-C", str(source), "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("shallow Git metadata")
    if (source / ".git/objects/info/alternates").exists() or (source / ".git").is_file():
        raise ValueError("external or indirect Git metadata")
    if command("git", "-C", str(source), "rev-parse", "HEAD") != revision:
        raise ValueError("source HEAD does not equal revision")
    command("git", "-C", str(source), "cat-file", "-e", f"{revision}^{{commit}}")
    if command("git", "-C", str(source), "status", "--porcelain"):
        raise ValueError("source index or worktree is dirty")
    origins = command("git", "-C", str(source), "remote", "get-url", "--all", "origin").splitlines()
    if identity.rstrip("/") not in {origin.rstrip("/") for origin in origins}:
        raise ValueError("repository identity mismatch")


def validate_runner(snapshot: Path, revision: str) -> None:
    if command("git", "-C", str(snapshot), "rev-parse", "HEAD") != revision:
        raise ValueError("snapshot HEAD mismatch")
    command("git", "-C", str(snapshot), "fsck", "--full")
    if (snapshot / ".git/objects/info/alternates").exists() or not (
        snapshot / "node_modules/.pnpm"
    ).is_dir():
        raise ValueError("snapshot is externally dependent or incomplete")
    cli = snapshot / "frontend/node_modules/.bin/playwright"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ValueError("frontend Playwright CLI missing")
    runtime_module().discover_playwright_browser(snapshot)
    for link in (snapshot / "frontend/node_modules").rglob("*"):
        if link.is_symlink() and not link.exists():
            raise ValueError("broken frontend dependency link")


def materialize(
    source: Path,
    revision: str,
    identity: str,
    output: Path,
    pnpm: str,
    pnpm_version: str,
    browser_bundle: Path,
) -> None:
    verify_source(source, revision, identity)
    if output.exists() or not browser_bundle.is_dir():
        raise ValueError("output exists or browser bundle is invalid")
    if command(pnpm, "--version") != pnpm_version:
        raise ValueError("pnpm version mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".runner.", dir=output.parent))
    try:
        command(
            "git",
            "clone",
            "--no-local",
            "--no-hardlinks",
            "--no-checkout",
            str(source),
            str(staging),
        )
        command("git", "checkout", "--detach", revision, cwd=staging)
        subprocess.run(
            [pnpm, "install", "--frozen-lockfile", "--offline"],
            cwd=staging,
            check=True,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(staging / "playwright-browser")},
        )
        shutil.copytree(browser_bundle, staging / "playwright-browser")
        validate_runner(staging, revision)
        browser = runtime_module().discover_playwright_browser(staging)
        browser_relative = str(browser.relative_to(staging))
        files = {relative: sha(staging / relative) for relative in CRITICAL}
        files[browser_relative] = sha(browser)
        manifest = {
            "schemaVersion": 1,
            "runnerRevision": revision,
            "repositoryIdentity": identity.rstrip("/"),
            "pnpmVersion": pnpm_version,
            "playwrightBrowserExecutable": browser_relative,
            "files": files,
        }
        (staging / "sugarkube-runner-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        )
        os.replace(staging, output)
        validate_runner(output, revision)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


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


def load_snapshot_config(staged: Path, snapshot: Path) -> dict:
    """Load approved rendered coordinates and point them at a staged snapshot."""
    runtime = runtime_module()
    config = runtime.load_config(staged / "etc/sugarkube/dspace-chat-synthetic.json")
    revision = config["runnerRevision"]
    if snapshot.is_symlink() or not snapshot.is_dir() or snapshot.name != revision:
        raise ValueError("runner snapshot must be a real exact-revision directory")
    config["runnerRoot"] = str(snapshot.parent)
    return config


def validate_snapshot(staged: Path, snapshot: Path) -> str:
    """Apply the runtime's complete runner contract to an installation input."""
    runtime = runtime_module()
    config = load_snapshot_config(staged, snapshot)
    runtime.validate_runner(config)
    return config["runnerRevision"]


def rooted(root: Path, absolute: str) -> Path:
    return root / Path(absolute).relative_to("/")


def install_runner(staged: Path, snapshot: Path, root: Path) -> tuple[Path, bool]:
    """Copy, revalidate, and atomically expose an immutable runner snapshot."""
    runtime = runtime_module()
    config = runtime.load_config(staged / "etc/sugarkube/dspace-chat-synthetic.json")
    revision = config["runnerRevision"]
    parent = rooted(root, config["runnerRoot"])
    destination = parent / revision
    rooted_config = dict(config, runnerRoot=str(parent))
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("runner revision destination is invalid")
        runtime.validate_runner(rooted_config)
        manifest = "sugarkube-runner-manifest.json"
        if (snapshot / manifest).read_bytes() != (destination / manifest).read_bytes():
            raise ValueError("existing runner manifest does not match snapshot")
        return destination, False
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=parent))
    temporary.rmdir()
    try:
        shutil.copytree(snapshot, temporary, symlinks=True)
        copied_config = dict(rooted_config, runnerRoot=str(temporary.parent))
        # Validation expects the immutable revision basename, so validate through
        # a private exact-name parent before the atomic destination rename.
        validation_parent = Path(tempfile.mkdtemp(prefix=".validate.", dir=parent))
        validation_runner = validation_parent / revision
        os.replace(temporary, validation_runner)
        try:
            runtime.validate_runner(dict(copied_config, runnerRoot=str(validation_parent)))
            os.replace(validation_runner, destination)
        finally:
            shutil.rmtree(validation_parent, ignore_errors=True)
        return destination, True
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def apply_installation(staged: Path, snapshot: Path, root: Path, asset_revision: str) -> None:
    """Install a fully validated runner and roll it back on later asset failure."""
    validate(staged)
    validate_snapshot(staged, snapshot)
    retained = root / "var/lib/sugarkube/dspace-chat-installations" / asset_revision
    if retained.exists():
        raise ValueError("exact retained revision already exists")
    runner, created = install_runner(staged, snapshot, root)
    try:
        install(staged, root, asset_revision)
    except Exception:
        shutil.rmtree(retained, ignore_errors=True)
        if created:
            shutil.rmtree(runner, ignore_errors=True)
        raise


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
    if root.resolve() != Path("/"):
        print("activation=not-queried")
        return 0
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
    if not ASSET_REVISION.fullmatch(revision):
        raise ValueError("revision must be a lowercase hexadecimal asset revision")
    validate(retained)
    current = retained.parent / "current"
    temporary = retained.parent / ".current.new"
    prepared = []
    backups = []
    try:
        # Prepare every replacement before changing the live installation.
        for target in ASSETS:
            destination = root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(f".{destination.name}.new")
            backup = destination.with_name(f".{destination.name}.old")
            temp.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
            shutil.copy2(retained / target, temp)
            prepared.append((destination, temp, backup))
        for destination, temp, backup in prepared:
            existed = destination.exists()
            if existed:
                os.replace(destination, backup)
            backups.append((destination, backup, existed))
            os.replace(temp, destination)
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(revision)
        os.replace(temporary, current)
    except Exception:
        for destination, backup, existed in reversed(backups):
            destination.unlink(missing_ok=True)
            if existed and backup.exists():
                os.replace(backup, destination)
        raise
    finally:
        temporary.unlink(missing_ok=True)
        for destination, temp, backup in prepared:
            temp.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)


def install(staged: Path, root: Path, revision: str) -> None:
    if not ASSET_REVISION.fullmatch(revision):
        raise ValueError("revision must be a lowercase hexadecimal asset revision")
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
        choices=("dry-run", "apply", "status", "rollback", "materialize"),
        default="dry-run",
    )
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--revision", default="97ab09f13fb098de928a878bf1fe9b8d13032cb5")
    parser.add_argument("--apply", action="store_true", help="authorize an explicit rollback")
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--repository-identity", default="https://github.com/democratizedspace/dspace.git"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pnpm")
    parser.add_argument("--pnpm-version")
    parser.add_argument("--browser-bundle", type=Path)
    parser.add_argument("--runner-snapshot", type=Path)
    args = parser.parse_args()
    if args.operation == "status":
        return status(args.root)
    if args.operation == "materialize":
        if not all((args.source, args.output, args.pnpm, args.pnpm_version, args.browser_bundle)):
            parser.error(
                "materialize requires source, output, pnpm, pnpm-version, and browser-bundle"
            )
        materialize(
            args.source.resolve(),
            args.revision,
            args.repository_identity,
            args.output.resolve(),
            args.pnpm,
            args.pnpm_version,
            args.browser_bundle.resolve(),
        )
        return 0
    if args.operation == "rollback":
        if not ASSET_REVISION.fullmatch(args.revision):
            raise ValueError("revision must be a lowercase hexadecimal asset revision")
        retained = args.root / "var/lib/sugarkube/dspace-chat-installations" / args.revision
        validate(retained)
        if not args.apply:
            print("validation=passed mutation=none rollback=authorization-required")
            return 0
        activate(retained, args.root, args.revision)
        return 0
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary)
        render(staged)
        validate(staged)
        if args.runner_snapshot is None:
            parser.error(f"{args.operation} requires --runner-snapshot")
        snapshot = args.runner_snapshot.absolute()
        validate_snapshot(staged, snapshot)
        if args.operation == "apply":
            asset_revision = hashlib.sha256((staged / "manifest.json").read_bytes()).hexdigest()
            apply_installation(staged, snapshot, args.root, asset_revision)
        else:
            print("validation=passed mutation=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
