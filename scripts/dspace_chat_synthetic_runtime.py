#!/usr/bin/env python3
"""Fail-closed, invocation-bound DSPACE synthetic producer lifecycle."""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
INVOCATION = re.compile(r"[0-9a-f]{32}")
APPROVED = ("3.1.1", "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2")
APPROVED_REPOSITORY_IDENTITY = "https://github.com/democratizedspace/dspace.git"
APPROVED_TOKEN_PLACE_ORIGIN = "https://staging.token.place"
APPROVED_TOKEN_PLACE_MODEL = "qwen3-8b-instruct"
SERVICE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
MAX_RESULT_BYTES = 16 * 1024
MAX_BROWSER_PATH_BYTES = 4096
MAX_CHILD_DIAGNOSTIC_BYTES = 16 * 1024
STDERR_DRAIN_GRACE_SECONDS = 0.25
REQUIRED = {
    "runnerRevision",
    "dspaceOrigin",
    "repositoryIdentity",
    "dspaceVersion",
    "dspaceSourceRevision",
    "identityContract",
    "providerConfigContract",
    "provider",
    "tokenPlaceOrigin",
    "tokenPlaceModel",
    "timeoutSeconds",
    "serviceAccount",
    "serviceGroup",
    "runnerRoot",
    "resultRoot",
    "metricPath",
    "metricsConsumer",
    "browserContract",
}
RUNNER_LOCAL = "runner-local-playwright-v1"
SYSTEM_CHROMIUM = "system-chromium-v1"


class Invalid(RuntimeError):
    """Bounded validation failure (message contains no input data)."""


def load_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or not REQUIRED <= value.keys()
    ):
        raise Invalid("configuration schema")
    string_keys = REQUIRED - {"timeoutSeconds", "browserContract"}
    if (
        any(not isinstance(value[key], str) for key in string_keys)
        or not isinstance(value["timeoutSeconds"], int)
        or isinstance(value["timeoutSeconds"], bool)
    ):
        raise Invalid("configuration value type")
    if not SHA.fullmatch(value["runnerRevision"]):
        raise Invalid("runner coordinate")
    manifest_sha = value.get("runnerManifestSha256")
    if manifest_sha is not None and (
        not isinstance(manifest_sha, str) or not SHA256.fullmatch(manifest_sha)
    ):
        raise Invalid("runner manifest coordinate")
    if value["repositoryIdentity"] != APPROVED_REPOSITORY_IDENTITY:
        raise Invalid("repository identity")
    if value["tokenPlaceOrigin"] != APPROVED_TOKEN_PLACE_ORIGIN:
        raise Invalid("token.place origin")
    if value["tokenPlaceModel"] != APPROVED_TOKEN_PLACE_MODEL:
        raise Invalid("token.place model")
    if any(
        not SERVICE_IDENTIFIER.fullmatch(value[key]) for key in ("serviceAccount", "serviceGroup")
    ):
        raise Invalid("service identifier")
    if value["identityContract"] != "build-info-v1":
        raise Invalid("identity contract")
    if value["providerConfigContract"] != "legacy-no-default-provider-v1":
        raise Invalid("provider contract must be selected explicitly")
    if (value["dspaceVersion"], value["dspaceSourceRevision"]) != APPROVED:
        raise Invalid("legacy provider contract coordinate")
    if value["provider"] != "token-place" or not 1 <= value["timeoutSeconds"] <= 600:
        raise Invalid("provider or timeout")
    if value["dspaceOrigin"] != "https://staging.democratized.space":
        raise Invalid("DSPACE origin")
    for key in ("runnerRoot", "resultRoot", "metricPath", "metricsConsumer"):
        if not Path(value[key]).is_absolute():
            raise Invalid("configured path")
    browser = value["browserContract"]
    if not isinstance(browser, dict) or browser.get("name") not in (RUNNER_LOCAL, SYSTEM_CHROMIUM):
        raise Invalid("browser contract must be selected explicitly")
    if browser["name"] == RUNNER_LOCAL:
        if set(browser) != {"name"}:
            raise Invalid("runner-local browser contract")
    else:
        required = {
            "name",
            "architecture",
            "launcherPath",
            "launcherRealpath",
            "launcherSha256",
            "executablePath",
            "executableRealpath",
            "executableSha256",
            "owner",
            "group",
            "mode",
            "launcherExecutableRelationship",
        }
        if set(browser) != required or any(not isinstance(browser[key], str) for key in required):
            raise Invalid("system browser contract")
        if (
            browser["architecture"] not in {"aarch64", "x86_64"}
            or browser["launcherExecutableRelationship"] not in {"same-file", "distinct-files"}
            or browser["mode"] != "0755"
            or not SHA256.fullmatch(browser["launcherSha256"])
            or not SHA256.fullmatch(browser["executableSha256"])
            or any(
                not Path(browser[key]).is_absolute()
                for key in (
                    "launcherPath",
                    "launcherRealpath",
                    "executablePath",
                    "executableRealpath",
                )
            )
        ):
            raise Invalid("system browser contract")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_root(root: Path) -> Path:
    """Return an existing real root without dereferencing caller identity."""
    if ".." in root.parts:
        raise Invalid("filesystem source root")
    supplied = Path(os.path.abspath(root))
    try:
        info = supplied.lstat()
        resolved = supplied.resolve(strict=True)
    except (OSError, RuntimeError):
        raise Invalid("filesystem source root") from None
    if not stat.S_ISDIR(info.st_mode) or supplied != resolved:
        raise Invalid("filesystem source root")
    return resolved


def discover_playwright_browser(runner: Path) -> Path:
    """Return Playwright's executable only when it is runner-local and usable."""
    browser_root = runner / "playwright-browser"
    try:
        browser_root_info = browser_root.lstat()
    except OSError:
        raise Invalid("Playwright browser discovery") from None
    if browser_root.is_symlink() or not stat.S_ISDIR(browser_root_info.st_mode):
        raise Invalid("Playwright browser discovery")
    completed = subprocess.run(
        [
            "/usr/bin/node",
            "-e",
            "const {chromium}=require('@playwright/test');"
            "const p=chromium.executablePath();"
            f"if(typeof p!=='string'||Buffer.byteLength(p)>{MAX_BROWSER_PATH_BYTES})"
            "process.exit(2);"
            "process.stdout.write(p);",
        ],
        cwd=runner / "frontend",
        env={"PLAYWRIGHT_BROWSERS_PATH": str(browser_root)},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    output = completed.stdout
    if not isinstance(output, bytes) or not output or len(output) > MAX_BROWSER_PATH_BYTES:
        raise Invalid("Playwright browser discovery")
    try:
        discovered = Path(output.decode("utf-8"))
        if not discovered.is_absolute():
            raise Invalid("Playwright browser discovery")
        resolved_root = browser_root.resolve(strict=True)
        resolved = discovered.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except Invalid:
        raise
    except (OSError, UnicodeError, ValueError):
        raise Invalid("Playwright browser discovery") from None
    info = discovered.lstat()
    if (
        discovered.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or not os.access(discovered, os.X_OK)
    ):
        raise Invalid("Playwright browser discovery")
    return resolved


def _rooted(root: Path, absolute: str) -> Path:
    coordinate = Path(absolute)
    if not coordinate.is_absolute() or ".." in coordinate.parts:
        raise Invalid("rooted coordinate")
    return root / coordinate.relative_to("/")


def validate_browser_contract(config: dict, runner: Path, root: Path = Path("/")) -> dict:
    """Validate and describe the explicitly selected browser without fallback."""
    contract = config["browserContract"]
    if contract["name"] == RUNNER_LOCAL:
        executable = discover_playwright_browser(runner)
        return {
            "name": RUNNER_LOCAL,
            "architecture": platform.machine(),
            "executablePath": str(executable.relative_to(runner)),
            "executableSha256": sha256(executable),
        }
    if contract["name"] != SYSTEM_CHROMIUM or platform.machine() != contract["architecture"]:
        raise Invalid("browser architecture or contract")
    root = normalize_root(root)
    validated = []
    for prefix in ("launcher", "executable"):
        configured = contract[f"{prefix}Path"]
        path = _rooted(root, configured)
        try:
            info = path.lstat()
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            owner = pwd.getpwuid(info.st_uid).pw_name
            group = grp.getgrgid(info.st_gid).gr_name
        except (OSError, KeyError, ValueError):
            raise Invalid("system browser provenance") from None
        expected_realpath = _rooted(root, contract[f"{prefix}Realpath"])
        if (
            path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or not os.access(path, os.X_OK)
            or resolved != expected_realpath
            or sha256(path) != contract[f"{prefix}Sha256"]
            or owner != contract["owner"]
            or group != contract["group"]
            or f"{stat.S_IMODE(info.st_mode):04o}" != contract["mode"]
        ):
            raise Invalid("system browser provenance")
        validated.append(resolved)
    same = validated[0].samefile(validated[1])
    if same != (contract["launcherExecutableRelationship"] == "same-file"):
        raise Invalid("system browser provenance relationship")
    return {
        "name": SYSTEM_CHROMIUM,
        "architecture": contract["architecture"],
        "launcherPath": contract["launcherPath"],
        "launcherRealpath": contract["launcherRealpath"],
        "launcherSha256": contract["launcherSha256"],
        "executablePath": contract["executablePath"],
        "executableRealpath": contract["executableRealpath"],
        "executableSha256": contract["executableSha256"],
        "owner": contract["owner"],
        "group": contract["group"],
        "mode": contract["mode"],
        "launcherExecutableRelationship": contract["launcherExecutableRelationship"],
    }


def runner_storage_identity(config: dict) -> str:
    """Return the immutable storage identity, separate from the Git revision."""
    revision = config["runnerRevision"]
    manifest_sha = config.get("runnerManifestSha256")
    return revision if manifest_sha is None else f"{revision}-{manifest_sha}"


def validate_runner(config: dict) -> Path:
    configured_root = Path(config["runnerRoot"])
    if not configured_root.is_absolute() or ".." in configured_root.parts:
        raise Invalid("runner path")
    runner_root = normalize_root(configured_root)
    runner = runner_root / config.get("_runnerStorageIdentity", runner_storage_identity(config))
    try:
        runner_info = runner.lstat()
        resolved_runner = runner.resolve(strict=True)
        resolved_runner.relative_to(runner_root)
    except (OSError, RuntimeError, ValueError):
        raise Invalid("runner path") from None
    if (
        not stat.S_ISDIR(runner_info.st_mode)
        or runner.is_symlink()
        or runner != resolved_runner
        or runner.parent != runner_root
    ):
        raise Invalid("runner path")
    runner = resolved_runner
    manifest_path = runner / "sugarkube-runner-manifest.json"
    expected_manifest_sha = config.get("runnerManifestSha256")
    if expected_manifest_sha is not None and sha256(manifest_path) != expected_manifest_sha:
        raise Invalid("runner manifest digest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    browser_relative = manifest.get("playwrightBrowserExecutable")
    if (
        manifest.get("schemaVersion") != 1
        or not isinstance(files, dict)
        or not files
        or manifest.get("runnerRevision") != config["runnerRevision"]
        or manifest.get("repositoryIdentity") != config["repositoryIdentity"]
        or manifest.get("browserContract") != config["browserContract"]
    ):
        raise Invalid("wrapper/config coordinate mismatch")
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise Invalid("critical file manifest")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not SHA256.fullmatch(expected)
        ):
            raise Invalid("critical file manifest")
    if config["browserContract"]["name"] == RUNNER_LOCAL:
        if not isinstance(browser_relative, str):
            raise Invalid("Playwright browser manifest")
        browser_path = Path(browser_relative)
        if (
            browser_path.is_absolute()
            or ".." in browser_path.parts
            or not browser_path.parts
            or browser_path.parts[0] != "playwright-browser"
            or browser_relative not in files
        ):
            raise Invalid("Playwright browser manifest")
    elif browser_relative is not None:
        raise Invalid("system browser manifest")
    git_metadata = runner / ".git"
    if git_metadata.is_symlink() or not git_metadata.is_dir():
        raise Invalid("complete Git metadata")
    git_environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    git_environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    )

    def runner_git(*arguments: str) -> subprocess.CompletedProcess[str]:
        """Run read-only Git with trust scoped to this exact validated runner."""
        return subprocess.run(
            ["git", "-c", f"safe.directory={runner}", "-C", str(runner), *arguments],
            env=git_environment,
            capture_output=True,
            text=True,
            check=True,
        )

    if runner_git("rev-parse", "HEAD").stdout.strip() != config["runnerRevision"]:
        raise Invalid("runner HEAD")
    if runner_git("status", "--porcelain", "--untracked-files=no").stdout:
        raise Invalid("runner tracked state")
    if (runner / ".git/objects/info/alternates").exists():
        raise Invalid("external object store")
    if runner_git("rev-parse", "--is-shallow-repository").stdout.strip() != "false":
        raise Invalid("shallow repository")
    runner_git("fsck", "--full")
    for relative, expected in files.items():
        target = runner / relative
        if target.is_symlink() or not target.is_file() or sha256(target) != expected:
            raise Invalid("critical file hash")
    required = {
        "scripts/run-remote-chat-smoke.mjs",
        "scripts/remote-chat-smoke-completion.mjs",
        "frontend/e2e/remote-chat-smoke.spec.ts",
        "frontend/playwright.config.ts",
        "frontend/scripts/utils/ensure-playwright-browsers.js",
        "package.json",
        "frontend/package.json",
        "pnpm-workspace.yaml",
        "pnpm-lock.yaml",
    }
    if not required <= files.keys():
        raise Invalid("critical file manifest")
    if not (runner / "node_modules/.pnpm").is_dir():
        raise Invalid("root pnpm store")
    cli = runner / "frontend/node_modules/.bin/playwright"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise Invalid("Playwright CLI")
    entrypoint = runner / "scripts/run-remote-chat-smoke.mjs"
    if not entrypoint.is_file():
        raise Invalid("runner entrypoint")
    if config["browserContract"]["name"] == RUNNER_LOCAL:
        discovered = discover_playwright_browser(runner)
        if discovered != (runner / browser_relative).resolve(strict=True):
            raise Invalid("Playwright browser manifest")
    return runner


def validate_dir(path: Path, uid: int, gid: int, mode: int) -> None:
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
        uid,
        gid,
        mode,
    ):
        raise Invalid("ownership or mode")


def read_result(path: Path, uid: int, gid: int) -> dict:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or (
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            )
            != (uid, gid, 0o600)
            or info.st_nlink != 1
        ):
            raise Invalid("current result provenance")
        if info.st_size > MAX_RESULT_BYTES:
            raise Invalid("current result size")
        contents = os.read(descriptor, MAX_RESULT_BYTES + 1)
        if len(contents) > MAX_RESULT_BYTES:
            raise Invalid("current result size")
        try:
            return json.loads(contents.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise Invalid("current result contract") from None
    finally:
        os.close(descriptor)


def cleanup_invocation(invocation_dir: Path) -> None:
    """Remove only direct children of this invocation, without following links."""
    try:
        entries = list(os.scandir(invocation_dir))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                os.rmdir(entry.path)
            else:
                os.unlink(entry.path)
        except OSError:
            pass
    try:
        invocation_dir.rmdir()
    except OSError:
        pass


def classify_missing_result(stderr: bytes, child_status: int, metadata: dict) -> tuple[str, dict]:
    """Classify bounded child diagnostics without retaining or returning their contents."""
    text = stderr.decode("utf-8", errors="replace").lower()
    if any(
        marker in text
        for marker in (
            "executable doesn't exist",
            "browsertype.launch: failed to launch",
            "browser.launch: failed to launch",
        )
    ):
        classification = "browser-executable-launch-failure"
    elif any(
        marker in text
        for marker in (
            "error loading config",
            "configuration file",
            "playwright.config",
            "unknown project",
        )
    ):
        classification = "playwright-configuration-failure"
    elif "result publication failed" in text:
        classification = "completion-publisher-failure"
    elif child_status == 0:
        classification = "current-result-missing-after-child-success"
    elif "journey completion was not confirmed" in text:
        classification = "test-failure-before-completion-publication"
    else:
        classification = "current-result-missing-after-child-failure"
    return classification, metadata


def bounded_stderr_run(
    argv: list[str], **kwargs
) -> tuple[subprocess.CompletedProcess, bytes, dict]:
    """Run a child while hashing and discarding stderr beyond a fixed in-memory prefix."""
    read_fd, write_fd = os.pipe()
    captured = bytearray()
    digest = hashlib.sha256()
    count = 0
    capture_lock = threading.Lock()

    def drain() -> None:
        nonlocal count
        with os.fdopen(read_fd, "rb", closefd=True) as stream:
            for block in iter(lambda: stream.read(8192), b""):
                with capture_lock:
                    count += len(block)
                    digest.update(block)
                    remaining = MAX_CHILD_DIAGNOSTIC_BYTES - len(captured)
                    if remaining > 0:
                        captured.extend(block[:remaining])

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        with os.fdopen(write_fd, "wb", closefd=True) as stream:
            completed = subprocess.run(argv, stderr=stream, **kwargs)
    finally:
        reader.join(STDERR_DRAIN_GRACE_SECONDS)
    with capture_lock:
        capture_complete = not reader.is_alive()
        captured_snapshot = bytes(captured)
        count_snapshot = count
        digest_snapshot = digest.hexdigest()
    return (
        completed,
        captured_snapshot,
        {
            "stderrBytes": count_snapshot,
            "stderrSha256": digest_snapshot,
            "stderrTruncated": count_snapshot > MAX_CHILD_DIAGNOSTIC_BYTES,
            "stderrCaptureComplete": capture_complete,
        },
    )


def archive_classification(
    root: Path, invocation: str, classification: str, metadata: dict
) -> None:
    """Atomically replace the single bounded classification record."""
    path = root / "latest-classification.json"
    payload = {
        "schemaVersion": 1,
        "invocation": invocation,
        "classification": classification,
        **metadata,
    }
    temporary = root / f".latest-classification-{invocation}.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run(config: dict) -> int:
    invocation = os.environ.get("INVOCATION_ID", "")
    if not INVOCATION.fullmatch(invocation):
        raise Invalid("systemd invocation identity")
    account = pwd.getpwnam(config["serviceAccount"])
    group = grp.getgrnam(config["serviceGroup"])
    if account.pw_gid != group.gr_gid:
        raise Invalid("service account/group")
    for executable in ("/usr/bin/python3", "git", "runuser", config["metricsConsumer"]):
        resolved = executable if Path(executable).is_absolute() else shutil.which(executable)
        if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
            raise Invalid("required executable")
    runner = validate_runner(config)
    browser = validate_browser_contract(config, runner)
    if (
        browser
        != json.loads((runner / "sugarkube-runner-manifest.json").read_text())["browserProvenance"]
    ):
        raise Invalid("runner browser provenance")
    root = Path(config["resultRoot"])
    validate_dir(root, 0, account.pw_gid, 0o710)
    invocation_dir = root / f"uid-{account.pw_uid}-{invocation}"
    with (root / ".lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Invalid("overlapping execution") from error
        if os.path.lexists(invocation_dir):
            raise Invalid("pre-existing invocation path")
        invocation_dir.mkdir(mode=0o770)
        try:
            os.chown(invocation_dir, 0, account.pw_gid)
            os.chmod(invocation_dir, 0o770)
            validate_dir(invocation_dir, 0, account.pw_gid, 0o770)
            result = invocation_dir / "result.json"
            started = int(time.time())
            argv = [
                "/usr/bin/node",
                str(runner / "scripts/run-remote-chat-smoke.mjs"),
                "--base-url",
                config["dspaceOrigin"],
                "--expected-version",
                config["dspaceVersion"],
                "--expected-revision",
                config["dspaceSourceRevision"],
                "--identity-contract",
                config["identityContract"],
                "--provider-config-contract",
                config["providerConfigContract"],
                "--expected-provider",
                config["provider"],
                "--expected-token-place-origin",
                config["tokenPlaceOrigin"],
                "--expected-token-place-model",
                config["tokenPlaceModel"],
                "--result-file",
                str(result),
                "--runner-revision",
                config["runnerRevision"],
            ]
            try:
                # Revalidate immediately before launch so drift cannot produce a current result.
                browser = validate_browser_contract(config, runner)
                child_env = {
                    "HOME": account.pw_dir,
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "LOGNAME": account.pw_name,
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "USER": account.pw_name,
                    "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                }
                if browser["name"] == RUNNER_LOCAL:
                    child_env["PLAYWRIGHT_BROWSERS_PATH"] = str(runner / "playwright-browser")
                else:
                    child_env["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"] = browser["executablePath"]
                completed, child_diagnostic, diagnostic_metadata = bounded_stderr_run(
                    ["runuser", "--user", config["serviceAccount"], "--", *argv],
                    cwd=runner,
                    stdout=subprocess.DEVNULL,
                    env=child_env,
                    timeout=config["timeoutSeconds"],
                    check=False,
                )
                ended = int(time.time())
                try:
                    payload = read_result(result, account.pw_uid, account.pw_gid)
                except FileNotFoundError:
                    classification, metadata = classify_missing_result(
                        child_diagnostic, completed.returncode, diagnostic_metadata
                    )
                    archive_classification(
                        root,
                        invocation,
                        classification,
                        {"childStatus": completed.returncode, **metadata},
                    )
                    raise Invalid(classification.replace("-", " "))
                expected_keys = {
                    "schemaVersion",
                    "journey",
                    "passed",
                    "executedAt",
                    "runnerRevision",
                    "transport",
                    "mutationEnabled",
                }
                if (
                    not isinstance(payload, dict)
                    or set(payload) != expected_keys
                    or payload.get("runnerRevision") != config["runnerRevision"]
                    or type(payload.get("passed")) is not bool
                    or type(payload.get("executedAt")) is not int
                    or not started <= payload["executedAt"] <= ended
                    or (completed.returncode == 0) != payload["passed"]
                ):
                    raise Invalid("current result contract")
                # The bounded consumer validates the schema and publishes atomically.
                subprocess.run(
                    [
                        "/usr/bin/python3",
                        config["metricsConsumer"],
                        "--result",
                        str(result),
                        "--output",
                        config["metricPath"],
                        "--runner-revision",
                        config["runnerRevision"],
                        "--environment",
                        "staging",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                print(
                    f"invocation={invocation} outcome=published "
                    f"child_status={completed.returncode} start={started} end={ended}"
                )
                return 0 if completed.returncode == 0 else 1
            except Invalid as error:
                print(
                    f"invocation={invocation} outcome=preserved "
                    f"reason={str(error).replace(' ', '-')} start={started}"
                )
                return 1
            except (OSError, subprocess.SubprocessError):
                print(
                    f"invocation={invocation} outcome=preserved "
                    f"reason=execution-error start={started}"
                )
                return 1
        finally:
            cleanup_invocation(invocation_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(load_config(args.config))
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError, Invalid):
        print("outcome=preserved reason=preflight")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
