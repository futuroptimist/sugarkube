#!/usr/bin/env python3
"""Fail-closed, invocation-bound DSPACE synthetic producer lifecycle."""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import json
import os
import pwd
import platform
import re
import shutil
import stat
import subprocess
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
REQUIRED = {
    "runnerRevision",
    "dspaceOrigin",
    "repositoryIdentity",
    "dspaceVersion",
    "dspaceSourceRevision",
    "identityContract",
    "providerConfigContract",
    "provider",
    "browserContract",
    "tokenPlaceOrigin",
    "tokenPlaceModel",
    "timeoutSeconds",
    "serviceAccount",
    "serviceGroup",
    "runnerRoot",
    "resultRoot",
    "metricPath",
    "metricsConsumer",
}


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
    validate_browser_contract_schema(value["browserContract"])
    return value


SYSTEM_BROWSER_KEYS = {
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
    "provenanceRelationship",
}


def validate_browser_contract_schema(contract: object) -> None:
    """Require one complete, unambiguous browser contract."""
    if not isinstance(contract, dict) or not isinstance(contract.get("name"), str):
        raise Invalid("browser contract selection")
    if contract["name"] == "runner-local-playwright-v1":
        if set(contract) != {"name"}:
            raise Invalid("runner-local browser contract")
        return
    if contract["name"] != "system-chromium-v1" or set(contract) != SYSTEM_BROWSER_KEYS:
        raise Invalid("browser contract selection")
    if any(not isinstance(contract[key], str) or not contract[key] for key in SYSTEM_BROWSER_KEYS):
        raise Invalid("system browser contract")
    if contract["architecture"] not in {"aarch64", "x86_64"}:
        raise Invalid("browser architecture")
    for key in ("launcherPath", "launcherRealpath", "executablePath", "executableRealpath"):
        if not Path(contract[key]).is_absolute():
            raise Invalid("system browser path")
    if not SHA256.fullmatch(contract["launcherSha256"]) or not SHA256.fullmatch(
        contract["executableSha256"]
    ):
        raise Invalid("system browser hash")
    if (
        contract["mode"] != "0755"
        or contract["provenanceRelationship"] != "distinct-package-files-v1"
    ):
        raise Invalid("system browser provenance")


def _rooted(root: Path, absolute: str) -> Path:
    return root / Path(absolute).relative_to("/")


def validate_system_browser(
    config: dict, root: Path = Path("/"), architecture: str | None = None
) -> dict:
    """Validate system browser coordinates beneath exactly ``root`` without mutation."""
    contract = config["browserContract"]
    validate_browser_contract_schema(contract)
    if contract["name"] != "system-chromium-v1":
        raise Invalid("system browser contract")
    if (architecture or platform.machine()) != contract["architecture"]:
        raise Invalid("browser architecture")
    try:
        expected_uid = pwd.getpwnam(contract["owner"]).pw_uid
        expected_gid = grp.getgrnam(contract["group"]).gr_gid
    except KeyError:
        raise Invalid("system browser ownership") from None
    paths = {}
    for kind in ("launcher", "executable"):
        path = _rooted(root, contract[f"{kind}Path"])
        expected_realpath = _rooted(root, contract[f"{kind}Realpath"])
        try:
            info = path.lstat()
            resolved = path.resolve(strict=True)
        except OSError:
            raise Invalid(f"system browser {kind}") from None
        if (
            path.is_symlink()
            or resolved != expected_realpath
            or not stat.S_ISREG(info.st_mode)
            or not os.access(path, os.X_OK)
            or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
            != (expected_uid, expected_gid, int(contract["mode"], 8))
            or sha256(path) != contract[f"{kind}Sha256"]
        ):
            raise Invalid(f"system browser {kind}")
        paths[kind] = path
    if paths["launcher"] == paths["executable"]:
        raise Invalid("system browser provenance relationship")
    return {
        "browserContract": contract["name"],
        "architecture": contract["architecture"],
        "launcherPath": contract["launcherPath"],
        "launcherSha256": contract["launcherSha256"],
        "executablePath": contract["executablePath"],
        "executableSha256": contract["executableSha256"],
        "owner": contract["owner"],
        "group": contract["group"],
        "mode": contract["mode"],
        "provenanceRelationship": contract["provenanceRelationship"],
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
            "if(typeof p!=='string'||"
            f"Buffer.byteLength(p)>{MAX_BROWSER_PATH_BYTES})process.exit(2);"
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


def validate_runner(config: dict) -> Path:
    runner = Path(config["runnerRoot"]) / config["runnerRevision"]
    manifest = json.loads((runner / "sugarkube-runner-manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    contract = config["browserContract"]
    browser_relative = manifest.get("playwrightBrowserExecutable")
    if (
        manifest.get("schemaVersion") != 1
        or not isinstance(files, dict)
        or not files
        or manifest.get("runnerRevision") != config["runnerRevision"]
        or manifest.get("repositoryIdentity") != config["repositoryIdentity"]
        or manifest.get("browserContract") != contract["name"]
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
    if contract["name"] == "runner-local-playwright-v1":
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
    elif browser_relative is not None or manifest.get("systemBrowser") != contract:
        raise Invalid("system browser manifest")
    git_metadata = runner / ".git"
    if git_metadata.is_symlink() or not git_metadata.is_dir():
        raise Invalid("complete Git metadata")
    if (
        subprocess.run(
            ["git", "-C", str(runner), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        != config["runnerRevision"]
    ):
        raise Invalid("runner HEAD")
    if subprocess.run(
        ["git", "-C", str(runner), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout:
        raise Invalid("runner tracked state")
    if (runner / ".git/objects/info/alternates").exists():
        raise Invalid("external object store")
    if (
        subprocess.run(
            ["git", "-C", str(runner), "rev-parse", "--is-shallow-repository"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        != "false"
    ):
        raise Invalid("shallow repository")
    subprocess.run(
        ["git", "-C", str(runner), "fsck", "--full"],
        capture_output=True,
        text=True,
        check=True,
    )
    for relative, expected in files.items():
        target = runner / relative
        if target.is_symlink() or not target.is_file() or sha256(target) != expected:
            raise Invalid("critical file hash")
    required = {
        "scripts/run-remote-chat-smoke.mjs",
        "scripts/remote-chat-smoke-completion.mjs",
        "frontend/e2e/remote-chat-smoke.spec.ts",
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
    if contract["name"] == "runner-local-playwright-v1":
        discovered = discover_playwright_browser(runner)
        if discovered != (runner / browser_relative).resolve(strict=True):
            raise Invalid("Playwright browser manifest")
    return runner


def browser_environment(config: dict, runner: Path) -> dict[str, str]:
    contract = config["browserContract"]
    if contract["name"] == "runner-local-playwright-v1":
        return {"PLAYWRIGHT_BROWSERS_PATH": str(runner / "playwright-browser")}
    validate_system_browser(config)
    return {"PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH": contract["executablePath"]}


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
    browser_env = browser_environment(config, runner)
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
                completed = subprocess.run(
                    ["runuser", "--user", config["serviceAccount"], "--", *argv],
                    cwd=runner,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={
                        "HOME": account.pw_dir,
                        "LANG": "C.UTF-8",
                        "LC_ALL": "C.UTF-8",
                        "LOGNAME": account.pw_name,
                        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        **browser_env,
                        "USER": account.pw_name,
                    },
                    timeout=config["timeoutSeconds"],
                    check=False,
                )
                ended = int(time.time())
                try:
                    payload = read_result(result, account.pw_uid, account.pw_gid)
                except FileNotFoundError:
                    raise Invalid("current result missing")
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
