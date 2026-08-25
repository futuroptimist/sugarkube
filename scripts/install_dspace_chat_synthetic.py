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
import stat
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
    "frontend/playwright.config.ts",
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
    browser_bundle: Path | None,
    browser_contract: dict,
    browser_source_root: Path,
) -> None:
    runtime = runtime_module()
    browser_source_root = runtime.normalize_root(browser_source_root)
    verify_source(source, revision, identity)
    if output.exists():
        raise ValueError("output exists")
    if browser_contract["name"] == runtime.RUNNER_LOCAL:
        if browser_bundle is None or not browser_bundle.is_dir():
            raise ValueError("browser bundle is invalid")
    elif browser_contract["name"] == runtime.SYSTEM_CHROMIUM:
        if browser_bundle is not None:
            raise ValueError("system browser contract forbids a browser bundle")
        # Validate host-owned inputs before creating the staging directory or
        # running dependency installation. Runner-local discovery intentionally
        # remains below, after its bundle has been copied into the snapshot.
        browser_provenance = runtime.validate_browser_contract(
            {"browserContract": browser_contract}, output, browser_source_root
        )
    else:
        raise ValueError("unsupported browser contract")
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
            env={
                **os.environ,
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                **(
                    {"PLAYWRIGHT_BROWSERS_PATH": str(staging / "playwright-browser")}
                    if browser_contract["name"] == runtime.RUNNER_LOCAL
                    else {}
                ),
            },
        )
        if browser_bundle is not None:
            shutil.copytree(browser_bundle, staging / "playwright-browser")
        validate_runner(staging, revision)
        if browser_contract["name"] == runtime.RUNNER_LOCAL:
            browser_provenance = runtime.validate_browser_contract(
                {"browserContract": browser_contract}, staging, browser_source_root
            )
        files = {relative: sha(staging / relative) for relative in CRITICAL}
        browser_relative = None
        if browser_contract["name"] == runtime.RUNNER_LOCAL:
            browser_relative = browser_provenance["executablePath"]
            files[browser_relative] = sha(staging / browser_relative)
        manifest = {
            "schemaVersion": 1,
            "runnerRevision": revision,
            "repositoryIdentity": identity.rstrip("/"),
            "pnpmVersion": pnpm_version,
            "playwrightBrowserExecutable": browser_relative,
            "browserContract": browser_contract,
            "browserProvenance": browser_provenance,
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
    try:
        tree_stat = tree.lstat()
    except OSError as error:
        raise ValueError("asset tree is missing or invalid") from error
    if tree.is_symlink() or not stat.S_ISDIR(tree_stat.st_mode):
        raise ValueError("asset tree must be a real directory")

    def regular_file(relative: str) -> Path:
        path = tree
        parts = Path(relative).parts
        for component in parts[:-1]:
            path /= component
            try:
                component_stat = path.lstat()
            except OSError as error:
                raise ValueError("asset path is missing or invalid") from error
            if path.is_symlink() or not stat.S_ISDIR(component_stat.st_mode):
                raise ValueError("asset path contains an invalid directory")
        path /= parts[-1]
        try:
            file_stat = path.lstat()
        except OSError as error:
            raise ValueError("asset file is missing or invalid") from error
        if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("asset file must be a real regular file")
        return path

    manifest = json.loads(regular_file("manifest.json").read_text())
    if set(manifest) != set(ASSETS):
        raise ValueError("asset manifest is incomplete")
    for target, expected in manifest.items():
        path = regular_file(target)
        if sha(path) != expected:
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


def validate_live_assets(root: Path, retained: Path, manifest: dict[str, str]) -> None:
    """Require every active asset to be the retained manifest's regular file."""
    for relative, expected in manifest.items():
        live = root
        try:
            for component in Path(relative).parts[:-1]:
                live /= component
                parent_info = live.lstat()
                if live.is_symlink() or not stat.S_ISDIR(parent_info.st_mode):
                    raise ValueError("live asset path contains an invalid directory")
            live /= Path(relative).parts[-1]
            live_info = live.lstat()
        except OSError as error:
            raise ValueError("live asset is missing or invalid") from error
        if live.is_symlink() or not stat.S_ISREG(live_info.st_mode) or sha(live) != expected:
            raise ValueError("live asset does not match current retained revision")
    config = "etc/sugarkube/dspace-chat-synthetic.json"
    if (root / config).read_bytes() != (retained / config).read_bytes():
        raise ValueError("live configuration does not match current retained revision")


def load_snapshot_config(staged: Path, snapshot: Path) -> dict:
    """Load approved rendered coordinates and point them at a staged snapshot."""
    runtime = runtime_module()
    config = runtime.load_config(staged / "etc/sugarkube/dspace-chat-synthetic.json")
    revision = config["runnerRevision"]
    if snapshot.is_symlink() or not snapshot.is_dir() or snapshot.name != revision:
        raise ValueError("runner snapshot must be a real exact-revision directory")
    config["runnerRoot"] = str(snapshot.parent)
    return config


def validate_snapshot(staged: Path, snapshot: Path, root: Path = Path("/")) -> str:
    """Apply the runtime's complete runner contract to an installation input."""
    runtime = runtime_module()
    config = load_snapshot_config(staged, snapshot)
    runner = runtime.validate_runner(config)
    provenance = runtime.validate_browser_contract(config, runner, root)
    manifest = json.loads((runner / "sugarkube-runner-manifest.json").read_text())
    if provenance != manifest.get("browserProvenance"):
        raise ValueError("runner browser provenance mismatch")
    return config["runnerRevision"]


def rooted(root: Path, absolute: str) -> Path:
    coordinate = Path(absolute)
    if not coordinate.is_absolute() or ".." in coordinate.parts:
        raise ValueError("rooted coordinate must be absolute and confined")
    return root / coordinate.relative_to("/")


def service_identity(config: dict, root: Path) -> tuple[int, int]:
    """Resolve the configured child identity, with a host-free rehearsal mapping."""
    if root.resolve() != Path("/"):
        # Alternate roots deliberately model a distinct child reached through
        # the configured service-group permissions, without requiring that
        # account or group to exist on the test/rehearsal host.
        return -1, os.getgid()
    import grp
    import pwd

    try:
        account = pwd.getpwnam(config["serviceAccount"])
        group = grp.getgrnam(config["serviceGroup"])
    except KeyError:
        raise ValueError("configured service identity is unavailable") from None
    if account.pw_gid != group.gr_gid:
        raise ValueError("configured service account primary group does not match service group")
    return account.pw_uid, group.gr_gid


def runner_access_paths(root: Path, runner_parent: Path) -> list[Path]:
    """Return only the application-owned parents needed to reach the runner."""
    base = rooted(root, "/var/lib/sugarkube")
    try:
        relative = runner_parent.relative_to(base)
    except ValueError:
        raise ValueError("runner parent must be within /var/lib/sugarkube") from None
    paths = [base]
    for component in relative.parts:
        paths.append(paths[-1] / component)
    return paths


def normalize_runner_access(config: dict, runner: Path, root: Path) -> None:
    """Make an immutable root-owned runner usable by the configured child group."""
    plan = runner_access_plan(config, runner, root)
    apply_runner_access_plan(plan)


def apply_runner_access_plan(
    plan: list[tuple[Path, int, int, int | None, bool]],
) -> None:
    """Apply only metadata fields that differ from the fully validated plan."""
    for path, uid, gid, mode, follow_symlinks in plan:
        info = path.lstat()
        if info.st_uid != uid or info.st_gid != gid:
            os.chown(path, uid, gid, follow_symlinks=follow_symlinks)
        if mode is not None and stat.S_IMODE(info.st_mode) != mode:
            path.chmod(mode)


def runner_access_plan(
    config: dict, runner: Path, root: Path
) -> list[tuple[Path, int, int, int | None, bool]]:
    """Validate the complete runner tree and return its metadata-only change plan."""
    _account_uid, group_gid = service_identity(config, root)
    owner_uid = 0 if root.resolve() == Path("/") else os.getuid()
    plan: list[tuple[Path, int, int, int | None, bool]] = []
    for parent in runner_access_paths(root, runner.parent):
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("runner parent is missing or invalid")
        plan.append((parent, owner_uid, group_gid, 0o710, True))
    if runner.is_symlink() or not runner.is_dir():
        raise ValueError("installed runner revision is missing or invalid")
    runner_real = runner.resolve(strict=True)
    for path in [runner, *runner.rglob("*")]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            try:
                target = path.resolve(strict=True)
                target.relative_to(runner_real)
            except (FileNotFoundError, RuntimeError, ValueError):
                raise ValueError(
                    "runner symlink target is missing or escapes runner tree"
                ) from None
            target_info = target.stat()
            if not (stat.S_ISDIR(target_info.st_mode) or stat.S_ISREG(target_info.st_mode)):
                raise ValueError("runner symlink target has an unsupported file type")
            plan.append((path, owner_uid, group_gid, None, False))
        elif stat.S_ISDIR(info.st_mode):
            plan.append((path, owner_uid, group_gid, 0o750, True))
        elif stat.S_ISREG(info.st_mode):
            executable = bool(stat.S_IMODE(info.st_mode) & 0o111)
            plan.append((path, owner_uid, group_gid, 0o750 if executable else 0o640, True))
        else:
            raise ValueError("runner contains an unsupported file type")
    return plan


def validate_runner_access(config: dict, runner: Path, root: Path) -> None:
    """Model access as the explicit account plus explicit service group."""
    account_uid, _group_gid = service_identity(config, root)
    plan = runner_access_plan(config, runner, root)
    desired = {path: mode for path, _uid, _gid, mode, _follow in plan}
    for path, owner_uid, expected_gid, expected_mode, _follow in plan:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            if info.st_uid != owner_uid or info.st_gid != expected_gid:
                raise ValueError("installed runner access metadata is invalid")
            target = path.resolve(strict=True)
            target_mode = desired[target]
            needed = 0o5 if target.is_dir() or target_mode & 0o111 else 0o4
            target_info = target.stat()
            effective = (
                (target_mode >> 6) if account_uid == target_info.st_uid else (target_mode >> 3)
            )
            if effective & needed != needed:
                raise ValueError("configured child cannot access runner symlink target")
            continue
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid != owner_uid or info.st_gid != expected_gid or mode != expected_mode:
            raise ValueError("installed runner access metadata is invalid")
        effective = (mode >> 6) if account_uid == info.st_uid else (mode >> 3)
        needed = 0o1 if expected_mode == 0o710 else (0o5 if path.is_dir() or mode & 0o111 else 0o4)
        if effective & needed != needed:
            raise ValueError("configured child cannot access installed runner")


def install_runner(staged: Path, snapshot: Path, root: Path) -> tuple[Path, bool]:
    """Copy, revalidate, and atomically expose an immutable runner snapshot."""
    runtime = runtime_module()
    config = runtime.load_config(staged / "etc/sugarkube/dspace-chat-synthetic.json")
    revision = config["runnerRevision"]
    parent = rooted(root, config["runnerRoot"])
    destination = parent / revision
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("runner revision destination is invalid")
        manifest = "sugarkube-runner-manifest.json"
        if (snapshot / manifest).read_bytes() != (destination / manifest).read_bytes():
            raise ValueError("existing runner manifest does not match snapshot")
        validate_snapshot(staged, destination, root)
        normalize_runner_access(config, destination, root)
        validate_runner_access(config, destination, root)
        return destination, False
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{revision}.", dir=parent))
    temporary.rmdir()
    try:
        shutil.copytree(snapshot, temporary, symlinks=True)
        # Validation expects the immutable revision basename, so validate through
        # a private exact-name parent before the atomic destination rename.
        validation_parent = Path(tempfile.mkdtemp(prefix=".validate.", dir=parent))
        validation_runner = validation_parent / revision
        os.replace(temporary, validation_runner)
        try:
            normalize_runner_access(config, validation_runner, root)
            validate_snapshot(staged, validation_runner, root)
            validate_runner_access(config, validation_runner, root)
            os.replace(validation_runner, destination)
            normalize_runner_access(config, destination, root)
            validate_runner_access(config, destination, root)
        finally:
            shutil.rmtree(validation_parent, ignore_errors=True)
        return destination, True
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def repair_runner_access(
    root: Path, revision: str, asset_revision: str, manifest_sha256: str, apply: bool
) -> int:
    """Validate, and only when explicitly authorized repair, one installed runner."""
    if not REVISION.fullmatch(revision) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("exact runner revision and manifest SHA-256 are required")
    installations = root / "var/lib/sugarkube/dspace-chat-installations"
    current = installations / "current"
    if not current.is_symlink():
        raise ValueError("current asset revision pointer is missing or invalid")
    current_revision = os.readlink(current)
    if (
        not ASSET_REVISION.fullmatch(asset_revision)
        or current_revision != asset_revision
        or Path(current_revision).parts != (current_revision,)
    ):
        raise ValueError("current asset revision pointer is invalid")
    retained = installations / asset_revision
    retained_manifest = validate(retained)
    validate_live_assets(root, retained, retained_manifest)
    config = runtime_module().load_config(retained / "etc/sugarkube/dspace-chat-synthetic.json")
    if config["runnerRevision"] != revision:
        raise ValueError("installed runner revision does not match authorization")
    runner = rooted(root, config["runnerRoot"]) / revision
    if runner.is_symlink() or not runner.is_dir():
        raise ValueError("installed runner revision is missing or invalid")
    manifest = runner / "sugarkube-runner-manifest.json"
    if manifest.is_symlink() or not manifest.is_file() or sha(manifest) != manifest_sha256:
        raise ValueError("installed runner manifest does not match authorization")
    validate_snapshot(retained, runner, root)
    plan = runner_access_plan(config, runner, root)
    access = "already-correct"
    for path, uid, gid, mode, _follow in plan:
        info = path.lstat()
        if info.st_uid != uid or info.st_gid != gid:
            access = "repair-required"
        if mode is not None and stat.S_IMODE(info.st_mode) != mode:
            access = "repair-required"
    if not apply:
        print(f"runnerRevision={revision}")
        print(f"runnerManifestSha256={manifest_sha256}")
        print(f"runnerAccess={access} mutation=none authorization=required")
        return 0
    if access == "already-correct":
        print("runnerAccess=already-correct mutation=none")
        return 0
    apply_runner_access_plan(plan)
    validate_snapshot(retained, runner, root)
    validate_runner_access(config, runner, root)
    if sha(manifest) != manifest_sha256:
        raise ValueError("runner content changed during access repair")
    print("runnerAccess=repaired mutation=metadata-only")
    return 0


def apply_installation(staged: Path, snapshot: Path, root: Path, asset_revision: str) -> None:
    """Install a fully validated runner and roll it back on later asset failure."""
    validate(staged)
    validate_snapshot(staged, snapshot, root)
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
    root = runtime_module().normalize_root(root)
    installations = root / "var/lib/sugarkube/dspace-chat-installations"
    current = installations / "current"
    live_paths = {target: root / target for target in ASSETS}
    if not installations.exists() and not any(
        path.exists() or path.is_symlink() for path in live_paths.values()
    ):
        for target in ASSETS:
            print(f"{target} sha256=missing")
        print("installation=absent")
        if root.resolve() != Path("/"):
            print("activation=not-queried")
            return 0
        return activation_status()

    if not current.is_symlink():
        raise ValueError("current asset revision pointer is missing or invalid")
    revision = os.readlink(current)
    target = Path(revision)
    if target.is_absolute() or len(target.parts) != 1 or not ASSET_REVISION.fullmatch(revision):
        raise ValueError("current asset revision pointer is invalid")
    retained = installations / revision
    if retained.is_symlink() or not retained.is_dir():
        raise ValueError("current retained asset revision is missing or invalid")
    manifest = validate(retained)
    validate_live_assets(root, retained, manifest)

    runtime = runtime_module()
    config = runtime.load_config(live_paths["etc/sugarkube/dspace-chat-synthetic.json"])
    runner_parent = rooted(root, config["runnerRoot"])
    expected_runner = runner_parent / config["runnerRevision"]
    if expected_runner.is_symlink() or not expected_runner.is_dir():
        raise ValueError("installed runner revision is missing or invalid")
    runner_manifest_path = expected_runner / "sugarkube-runner-manifest.json"
    if runner_manifest_path.is_symlink() or not runner_manifest_path.is_file():
        raise ValueError("installed runner manifest is missing or invalid")
    runner_manifest = json.loads(runner_manifest_path.read_text())
    if (
        not isinstance(runner_manifest.get("pnpmVersion"), str)
        or not runner_manifest["pnpmVersion"]
    ):
        raise ValueError("installed runner pnpm provenance is invalid")
    if config["browserContract"]["name"] == runtime.RUNNER_LOCAL and (
        not isinstance(runner_manifest.get("playwrightBrowserExecutable"), str)
        or not runner_manifest["playwrightBrowserExecutable"]
    ):
        raise ValueError("installed runner browser provenance is invalid")

    rooted_config = dict(config, runnerRoot=str(runner_parent))
    runner = runtime.validate_runner(rooted_config)
    if runner != expected_runner:
        raise ValueError("installed runner validation returned an unexpected revision")
    provenance = runtime.validate_browser_contract(rooted_config, runner, root)
    if provenance != runner_manifest.get("browserProvenance"):
        raise ValueError("installed runner browser provenance is invalid")

    print(f"assetRevision={revision}")
    for target_name, path in live_paths.items():
        print(f"{target_name} sha256={sha(path)}")
    print("runnerValidation=passed")
    print(f"runnerRevision={config['runnerRevision']}")
    print(f"runnerManifestSha256={sha(runner_manifest_path)}")
    for key in (
        "dspaceVersion",
        "dspaceSourceRevision",
        "repositoryIdentity",
        "identityContract",
        "providerConfigContract",
        "provider",
        "tokenPlaceOrigin",
        "tokenPlaceModel",
        "dspaceOrigin",
    ):
        print(f"{key}={config[key]}")
    print(f"pnpmVersion={runner_manifest['pnpmVersion']}")
    playwright_executable = runner_manifest.get("playwrightBrowserExecutable") or "none"
    print(f"playwrightBrowserExecutable={playwright_executable}")
    print(f"browserContract={config['browserContract']['name']}")
    print(f"browserArchitecture={provenance['architecture']}")
    print(f"browserExecutablePath={provenance['executablePath']}")
    print(f"browserExecutableSha256={provenance['executableSha256']}")
    if provenance["name"] == runtime.SYSTEM_CHROMIUM:
        print(f"browserLauncherPath={provenance['launcherPath']}")
        print(f"browserLauncherSha256={provenance['launcherSha256']}")
    if root.resolve() != Path("/"):
        print("activation=not-queried")
        return 0
    return activation_status()


def activation_status() -> int:
    """Report systemd state without changing the manager or its units."""
    for unit in ("dspace-chat-synthetic.service", "dspace-chat-synthetic.timer"):
        states = []
        for inspection in ("is-active", "is-enabled"):
            result = (
                subprocess.run(
                    ["systemctl", inspection, unit],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                if shutil.which("systemctl")
                else None
            )
            state = result.stdout.strip()[:128] if result else "unknown"
            states.append(f"{inspection.removeprefix('is-')}={state}")
        print(f"{unit} {' '.join(states)}")
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
        choices=(
            "dry-run",
            "apply",
            "status",
            "rollback",
            "repair-runner-access",
            "materialize",
        ),
        default="dry-run",
    )
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--revision", default="97ab09f13fb098de928a878bf1fe9b8d13032cb5")
    parser.add_argument("--apply", action="store_true", help="authorize an explicit mutation")
    parser.add_argument("--runner-manifest-sha256")
    parser.add_argument("--asset-revision")
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--repository-identity", default="https://github.com/democratizedspace/dspace.git"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pnpm")
    parser.add_argument("--pnpm-version")
    parser.add_argument("--browser-bundle", type=Path)
    parser.add_argument("--browser-source-root", type=Path)
    parser.add_argument("--runner-snapshot", type=Path)
    args = parser.parse_args()
    runtime = runtime_module()
    args.root = runtime.normalize_root(args.root)
    if args.operation == "status":
        return status(args.root)
    if args.operation == "repair-runner-access":
        if args.runner_manifest_sha256 is None or args.asset_revision is None:
            parser.error(
                "repair-runner-access requires --asset-revision and --runner-manifest-sha256"
            )
        return repair_runner_access(
            args.root,
            args.revision,
            args.asset_revision,
            args.runner_manifest_sha256,
            args.apply,
        )
    if args.operation == "materialize":
        if not all((args.source, args.output, args.pnpm, args.pnpm_version)):
            parser.error("materialize requires source, output, pnpm, and pnpm-version")
        browser_contract = runtime.load_config(ROOT / "config/dspace-chat-synthetic.json")[
            "browserContract"
        ]
        if browser_contract["name"] == runtime.SYSTEM_CHROMIUM and args.browser_source_root is None:
            parser.error("system browser materialize requires --browser-source-root")
        materialize(
            args.source.resolve(),
            args.revision,
            args.repository_identity,
            args.output.resolve(),
            args.pnpm,
            args.pnpm_version,
            args.browser_bundle.resolve() if args.browser_bundle else None,
            browser_contract,
            args.browser_source_root if args.browser_source_root else Path("/"),
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
    # The system contract is independent of the copied runner. Check it before
    # rendering assets (and therefore before any installation-side output).
    configured = runtime.load_config(ROOT / "config/dspace-chat-synthetic.json")
    if configured["browserContract"]["name"] == runtime.SYSTEM_CHROMIUM:
        runtime.validate_browser_contract(configured, Path("."), args.root)
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary)
        render(staged)
        validate(staged)
        if args.runner_snapshot is None:
            parser.error(f"{args.operation} requires --runner-snapshot")
        snapshot = args.runner_snapshot.absolute()
        validate_snapshot(staged, snapshot, args.root)
        if args.operation == "apply":
            asset_revision = hashlib.sha256((staged / "manifest.json").read_bytes()).hexdigest()
            apply_installation(staged, snapshot, args.root, asset_revision)
        else:
            print("validation=passed mutation=none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
