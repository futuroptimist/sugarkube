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
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
INVOCATION = re.compile(r"[0-9a-f]{32}")
APPROVED = ("3.1.1", "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2")
REQUIRED = {
    "runnerRevision",
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
}


class Invalid(RuntimeError):
    """Bounded validation failure (message contains no input data)."""


def load_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not REQUIRED <= value.keys():
        raise Invalid("configuration schema")
    if not SHA.fullmatch(value["runnerRevision"]):
        raise Invalid("runner coordinate")
    if value["identityContract"] != "build-info-v1":
        raise Invalid("identity contract")
    if value["providerConfigContract"] != "legacy-no-default-provider-v1":
        raise Invalid("provider contract must be selected explicitly")
    if (value["dspaceVersion"], value["dspaceSourceRevision"]) != APPROVED:
        raise Invalid("legacy provider contract coordinate")
    if value["provider"] != "token-place" or not 1 <= value["timeoutSeconds"] <= 600:
        raise Invalid("provider or timeout")
    for key in ("runnerRoot", "resultRoot", "metricPath", "metricsConsumer"):
        if not Path(value[key]).is_absolute():
            raise Invalid("configured path")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_runner(config: dict) -> Path:
    runner = Path(config["runnerRoot"]) / config["runnerRevision"]
    manifest = json.loads((runner / "sugarkube-runner-manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("runnerRevision") != config["runnerRevision"]
        or manifest.get("repositoryIdentity") != config["repositoryIdentity"]
    ):
        raise Invalid("wrapper/config coordinate mismatch")
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
    for relative, expected in manifest.get("files", {}).items():
        target = runner / relative
        if target.is_symlink() or not target.is_file() or sha256(target) != expected:
            raise Invalid("critical file hash")
    if not (runner / "node_modules/.pnpm").is_dir():
        raise Invalid("root pnpm store")
    cli = runner / "node_modules/.bin/playwright"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise Invalid("Playwright CLI")
    return runner


def validate_dir(path: Path, uid: int, gid: int, mode: int) -> None:
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
        uid,
        gid,
        mode,
    ):
        raise Invalid("ownership or mode")


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
    root = Path(config["resultRoot"])
    validate_dir(root, 0, account.pw_gid, 0o710)
    lock = (root / ".lock").open("a+b")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        raise Invalid("overlapping execution") from error
    invocation_dir = root / f"uid-{account.pw_uid}-{invocation}"
    if invocation_dir.exists():
        raise Invalid("pre-existing invocation path")
    invocation_dir.mkdir(mode=0o770)
    os.chown(invocation_dir, 0, account.pw_gid)
    result = invocation_dir / "result.json"
    started = int(time.time())
    argv = [
        str(runner / "node_modules/.bin/playwright"),
        "test",
        "tests/remote-chat-smoke.spec.ts",
        "--",
        "--result-file",
        str(result),
        "--runner-revision",
        config["runnerRevision"],
        "--identity-contract",
        config["identityContract"],
        "--provider-config-contract",
        config["providerConfigContract"],
        "--provider",
        config["provider"],
        "--token-place-origin",
        config["tokenPlaceOrigin"],
        "--token-place-model",
        config["tokenPlaceModel"],
    ]
    try:
        completed = subprocess.run(
            ["runuser", "--user", config["serviceAccount"], "--", *argv],
            cwd=runner,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=config["timeoutSeconds"],
            check=False,
        )
        ended = int(time.time())
        if not result.is_file():
            raise Invalid("current result missing")
        info = result.stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
            account.pw_uid,
            account.pw_gid,
            0o600,
        ) or not started <= int(info.st_mtime) <= ended + 1:
            raise Invalid("current result provenance")
        # The bounded consumer validates the exact JSON schema and publishes atomically.
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
        summary = (
            f"invocation={invocation} outcome=published "
            f"child_status={completed.returncode} start={started} end={ended}"
        )
        print(summary)
        return 0 if completed.returncode == 0 else 1
    except (OSError, subprocess.SubprocessError, Invalid):
        print(
            f"invocation={invocation} outcome=preserved "
            f"reason=invalid-current-result start={started}"
        )
        return 1
    finally:
        if result.exists() and result.parent == invocation_dir:
            result.unlink()
        if invocation_dir.exists():
            invocation_dir.rmdir()


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
