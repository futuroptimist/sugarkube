#!/usr/bin/env python3
"""Fail-closed, invocation-bound DSPACE /chat synthetic producer."""

import argparse
import datetime as dt
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
import tempfile
import time
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
INVOCATION = re.compile(r"[0-9a-f]{32}")
APPROVED = ("3.1.1", "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2", "legacy-no-default-provider-v1")
CONFIG_KEYS = {
    "schemaVersion",
    "environment",
    "runnerRevision",
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
    "lockPath",
    "runnerCommand",
    "runnerSpec",
}
RESULT_KEYS = {
    "schemaVersion",
    "journey",
    "passed",
    "executedAt",
    "completedAt",
    "invocationId",
    "runnerRevision",
    "transport",
    "mutationEnabled",
}


class SyntheticError(RuntimeError):
    pass


def utc(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS:
        raise SyntheticError("configuration does not match the exact schema")
    if value["schemaVersion"] != 1 or value["environment"] != "staging":
        raise SyntheticError("only staging schema v1 is supported")
    for key in ("runnerRevision", "dspaceSourceRevision"):
        if not isinstance(value[key], str) or not SHA.fullmatch(value[key]):
            raise SyntheticError(f"invalid {key}")
    if value["identityContract"] != "build-info-v1":
        raise SyntheticError("identity contract must be selected explicitly")
    coordinates = (
        value["dspaceVersion"],
        value["dspaceSourceRevision"],
        value["providerConfigContract"],
    )
    if coordinates != APPROVED:
        raise SyntheticError("provider-config contract is not approved for these exact coordinates")
    if (
        value["provider"] != "token-place"
        or value["tokenPlaceOrigin"] != "https://staging.token.place"
        or value["tokenPlaceModel"] != "qwen3-8b-instruct"
    ):
        raise SyntheticError("provider coordinates mismatch")
    if type(value["timeoutSeconds"]) is not int or not 30 <= value["timeoutSeconds"] <= 300:
        raise SyntheticError("timeout must be bounded from 30 through 300 seconds")
    for key in ("runnerRoot", "resultRoot", "metricPath", "lockPath"):
        if not Path(value[key]).is_absolute() or "$" in value[key]:
            raise SyntheticError(f"{key} must be an exact absolute path")
    return value


def check_mode(path: Path, uid: int, gid: int, mode: int, label: str) -> None:
    info = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
        uid,
        gid,
        mode,
    ):
        raise SyntheticError(f"{label} ownership or mode mismatch")


def verify_runner(config: dict) -> Path:
    runner = Path(config["runnerRoot"]) / config["runnerRevision"]
    manifest_path = runner / "sugarkube-runner-manifest.json"
    if not runner.is_dir() or not (runner / ".git").is_dir() or not manifest_path.is_file():
        raise SyntheticError("runner or complete Git metadata missing")

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(runner), *args], text=True, capture_output=True, check=False
        )

    head = git("rev-parse", "HEAD")
    if head.returncode or head.stdout.strip() != config["runnerRevision"]:
        raise SyntheticError("runner commit mismatch")
    if git("status", "--porcelain=v1", "--untracked-files=no").stdout:
        raise SyntheticError("runner tracked/index state is dirty")
    if git("fsck", "--full", "--no-dangling").returncode:
        raise SyntheticError("runner Git objects are incomplete")
    alternates = runner / ".git/objects/info/alternates"
    if (
        alternates.exists()
        or git("config", "--get", "extensions.worktreeConfig").stdout.strip() == "true"
    ):
        raise SyntheticError("runner depends on an external Git object store")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("runnerRevision") != config["runnerRevision"] or not isinstance(
        manifest.get("files"), dict
    ):
        raise SyntheticError("runner manifest coordinates mismatch")
    for relative, expected in manifest["files"].items():
        target = runner / relative
        if (
            not target.is_file()
            or target.is_symlink()
            or hashlib.sha256(target.read_bytes()).hexdigest() != expected
        ):
            raise SyntheticError("critical runner file hash mismatch")
    store = runner / "node_modules/.pnpm"
    frontend = runner / "apps/web/node_modules"
    command = runner / config["runnerCommand"]
    spec = runner / config["runnerSpec"]
    if not store.is_dir() or not any(store.iterdir()):
        raise SyntheticError("root pnpm store missing")
    if not frontend.is_dir() or any(
        link.is_symlink() and not link.exists() for link in frontend.rglob("*")
    ):
        raise SyntheticError("frontend dependency link is broken")
    if not command.is_file() or not os.access(command, os.X_OK) or not spec.is_file():
        raise SyntheticError("Playwright CLI/shim or smoke spec missing")
    probe = subprocess.run(
        [str(command), "--version"],
        cwd=runner,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if probe.returncode:
        raise SyntheticError("Playwright CLI/shim resolution failed")
    return runner


def valid_result(
    path: Path, config: dict, invocation: str, started: int, ended: int, uid: int, gid: int
) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
        ) != (uid, gid, 0o600):
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
        return (
            isinstance(value, dict)
            and set(value) == RESULT_KEYS
            and value["schemaVersion"] == 1
            and value["journey"] == "/chat"
            and type(value["passed"]) is bool
            and value["runnerRevision"] == config["runnerRevision"]
            and value["invocationId"] == invocation
            and value["transport"] == "intercepted"
            and value["mutationEnabled"] is False
            and type(value["executedAt"]) is int
            and type(value["completedAt"]) is int
            and started <= value["executedAt"] <= value["completedAt"] <= ended
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return False


def publish_metric(path: Path, passed: bool, timestamp: int) -> None:
    labels = 'application="dspace",environment="staging",cluster="sugarkube-int"'
    content = (
        "# HELP dspace_chat_synthetic_success Last executed isolated /chat result.\n"
        "# TYPE dspace_chat_synthetic_success gauge\n"
        f"dspace_chat_synthetic_success{{{labels}}} {int(passed)}\n"
        "# HELP dspace_chat_synthetic_timestamp_seconds Unix time of the last execution.\n"
        "# TYPE dspace_chat_synthetic_timestamp_seconds gauge\n"
        f"dspace_chat_synthetic_timestamp_seconds{{{labels}}} {timestamp}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(config: dict) -> int:
    invocation = os.environ.get("INVOCATION_ID", "")
    if not INVOCATION.fullmatch(invocation):
        raise SyntheticError("a valid systemd INVOCATION_ID is required")
    account, group = pwd.getpwnam(config["serviceAccount"]), grp.getgrnam(config["serviceGroup"])
    if account.pw_gid != group.gr_gid:
        raise SyntheticError("service account/group mismatch")
    runner = verify_runner(config)
    root = Path(config["resultRoot"])
    check_mode(root, 0, group.gr_gid, 0o710, "result root")
    lock_path = Path(config["lockPath"])
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SyntheticError("overlapping execution rejected")
    result_dir = root / f"{account.pw_name}-{invocation}"
    if result_dir.exists():
        raise SyntheticError("pre-existing invocation path rejected")
    result_dir.mkdir(mode=0o770)
    os.chown(result_dir, 0, group.gr_gid)
    check_mode(result_dir, 0, group.gr_gid, 0o770, "invocation directory")
    result = result_dir / "result.json"
    started = int(time.time())
    argv = [
        str(runner / config["runnerCommand"]),
        "test",
        config["runnerSpec"],
        "--",
        "--result",
        str(result),
        "--invocation-id",
        invocation,
        "--started-at",
        utc(started),
        "--identity-contract",
        config["identityContract"],
        "--provider-config-contract",
        config["providerConfigContract"],
        "--provider",
        config["provider"],
        "--expected-version",
        config["dspaceVersion"],
        "--expected-revision",
        config["dspaceSourceRevision"],
        "--expected-token-place-origin",
        config["tokenPlaceOrigin"],
        "--expected-token-place-model",
        config["tokenPlaceModel"],
    ]
    command = (
        argv
        if os.environ.get("SUGARKUBE_SYNTHETIC_TEST_DIRECT") == "1"
        else ["runuser", "--user", account.pw_name, "--", *argv]
    )
    try:
        completed = subprocess.run(
            command,
            cwd=runner,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=config["timeoutSeconds"],
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None
    ended = int(time.time())
    usable = completed is not None and valid_result(
        result, config, invocation, started, ended, account.pw_uid, group.gr_gid
    )
    if usable:
        publish_metric(Path(config["metricPath"]), json.loads(result.read_text())["passed"], ended)
    shutil.rmtree(result_dir)  # exact invocation-owned path only
    print(
        "dspace-chat-synthetic "
        f"invocation={invocation} start={utc(started)} end={utc(ended)} "
        f"result={'published' if usable else 'preserved'}"
    )
    return 0 if usable else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=Path("/etc/sugarkube/dspace-chat-synthetic.json")
    )
    args = parser.parse_args()
    try:
        return execute(load_config(args.config))
    except (
        SyntheticError,
        OSError,
        KeyError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"dspace-chat-synthetic: rejected: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
