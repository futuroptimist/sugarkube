#!/usr/bin/env python3
"""Fail-closed, invocation-bound DSPACE synthetic producer."""

import argparse
import fcntl
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
INVOCATION = re.compile(r"[0-9a-f]{32}")
APPROVED_LEGACY = ("3.1.1", "22f506e07e0b5abfd0cf756e9c5827c0458fb4b2")
REQUIRED = {
    "runner_revision",
    "dspace_version",
    "dspace_source_revision",
    "identity_contract",
    "provider_config_contract",
    "provider",
    "origin",
    "model",
    "timeout_seconds",
    "service_user",
    "service_group",
    "runner_root",
    "result_root",
    "metric_path",
    "wrapper_path",
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_config(path: Path) -> dict:
    value = json.loads(path.read_text())
    missing = REQUIRED - value.keys()
    if missing:
        raise ValueError("configuration lacks explicit required fields")
    if not SHA.fullmatch(value["runner_revision"]) or not SHA.fullmatch(
        value["dspace_source_revision"]
    ):
        raise ValueError("coordinates require full commit hashes")
    if value["identity_contract"] != "build-info-v1":
        raise ValueError("unsupported explicit identity contract")
    if value["provider_config_contract"] != "legacy-no-default-provider-v1":
        raise ValueError("unsupported explicit provider configuration contract")
    if (value["dspace_version"], value["dspace_source_revision"]) != APPROVED_LEGACY:
        raise ValueError("legacy provider contract is restricted to approved DSPACE coordinates")
    if not 1 <= int(value["timeout_seconds"]) <= 300:
        raise ValueError("timeout is outside the bounded range")
    for key in ("runner_root", "result_root", "metric_path", "wrapper_path"):
        if not Path(value[key]).is_absolute() or "$" in value[key]:
            raise ValueError(f"{key} must be an absolute resolved path")
    return value


def check_dir(path: Path, uid: int, gid: int, mode: int) -> None:
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
        uid,
        gid,
        mode,
    ):
        raise ValueError(f"unsafe ownership or mode for {path}")


def validate_runner(config: dict) -> Path:
    runner = Path(config["runner_root"]) / config["runner_revision"]
    manifest = json.loads((runner / "sugarkube-runner-manifest.json").read_text())
    if manifest.get("revision") != config["runner_revision"]:
        raise ValueError("wrapper/config/runner coordinate mismatch")
    if (
        subprocess.check_output(["git", "-C", str(runner), "rev-parse", "HEAD"], text=True).strip()
        != config["runner_revision"]
    ):
        raise ValueError("runner HEAD mismatch")
    if subprocess.run(
        ["git", "-C", str(runner), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout:
        raise ValueError("runner tracked/index state is dirty")
    if (runner / ".git/objects/info/alternates").exists() or not (
        runner / "node_modules/.pnpm"
    ).is_dir():
        raise ValueError("runner is incomplete or externally dependent")
    for relative, expected in manifest.get("files", {}).items():
        import hashlib

        actual = hashlib.sha256((runner / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("critical runner file hash mismatch")
    cli = runner / "node_modules/.bin/playwright"
    if (
        not cli.exists()
        or not os.access(cli, os.X_OK)
        or (cli.is_symlink() and not cli.resolve().exists())
    ):
        raise ValueError("Playwright CLI/shim is invalid")
    subprocess.run(
        ["node", "-e", "require.resolve('@playwright/test')"],
        cwd=runner,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return runner


def metric(config: dict, passed: bool, timestamp: int) -> bytes:
    labels = 'application="dspace",environment="staging",cluster="sugarkube-int"'
    return (
        "# HELP dspace_chat_synthetic_success Last executed isolated /chat result.\n"
        "# TYPE dspace_chat_synthetic_success gauge\n"
        f"dspace_chat_synthetic_success{{{labels}}} {int(passed)}\n"
        "# HELP dspace_chat_synthetic_timestamp_seconds Unix time of the last execution.\n"
        "# TYPE dspace_chat_synthetic_timestamp_seconds gauge\n"
        f"dspace_chat_synthetic_timestamp_seconds{{{labels}}} {timestamp}\n"
    ).encode()


def publish(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".dspace-chat.", dir=path.parent)
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.fchmod(fd, 0o644)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=Path("/etc/sugarkube/dspace-chat-synthetic.json")
    )
    args = parser.parse_args()
    invocation = os.environ.get("INVOCATION_ID", "")
    if not INVOCATION.fullmatch(invocation):
        parser.error("a valid systemd INVOCATION_ID is required")
    started, start_epoch = utc(), int(time.time())
    config = load_config(args.config)
    account = pwd.getpwnam(config["service_user"])
    result_root = Path(config["result_root"])
    metric_path = Path(config["metric_path"])
    lock = os.open(result_root.parent / "dspace-chat-synthetic.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"invocation={invocation} outcome=overlap-rejected start={started}")
        return 75
    invocation_dir = result_root / f"{config['service_user']}-{invocation}"
    result = invocation_dir / "result.json"
    try:
        check_dir(result_root, 0, account.pw_gid, 0o710)
        if invocation_dir.exists():
            raise ValueError("invocation result path already exists")
        runner = validate_runner(config)
        invocation_dir.mkdir(mode=0o770)
        os.chown(invocation_dir, 0, account.pw_gid)
        argv = [
            str(runner / "node_modules/.bin/playwright"),
            "test",
            "tests/remote-chat-smoke.spec.ts",
            "--",
            "--provider",
            config["provider"],
            "--origin",
            config["origin"],
            "--model",
            config["model"],
            "--identity-contract",
            config["identity_contract"],
            "--provider-config-contract",
            config["provider_config_contract"],
            "--result",
            str(result),
            "--runner-revision",
            config["runner_revision"],
            "--invocation-id",
            invocation,
        ]

        def demote():
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)

        try:
            subprocess.run(
                argv,
                cwd=runner,
                timeout=config["timeout_seconds"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=demote,
            )
        except (OSError, subprocess.TimeoutExpired):
            print(
                f"invocation={invocation} outcome=no-consumable-result start={started} end={utc()}"
            )
            return 1
        info = result.stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (
            account.pw_uid,
            account.pw_gid,
            0o600,
        ):
            raise ValueError("unsafe result ownership or mode")
        value = json.loads(result.read_text())
        end_epoch = int(time.time())
        if set(value) != {
            "schemaVersion",
            "passed",
            "runnerRevision",
            "invocationId",
            "startedAt",
            "endedAt",
        }:
            raise ValueError("malformed bounded result")
        if (
            value["schemaVersion"] != 1
            or type(value["passed"]) is not bool
            or value["runnerRevision"] != config["runner_revision"]
            or value["invocationId"] != invocation
        ):
            raise ValueError("result binding mismatch")
        if not start_epoch <= value["startedAt"] <= value["endedAt"] <= end_epoch:
            raise ValueError("result is outside invocation window")
        publish(metric_path, metric(config, value["passed"], end_epoch))
        passed_summary = str(value["passed"]).lower()
        print(
            f"invocation={invocation} outcome=published "
            f"passed={passed_summary} start={started} end={utc()}"
        )
        return 0 if value["passed"] else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError):
        print(f"invocation={invocation} outcome=no-consumable-result start={started} end={utc()}")
        return 1
    finally:
        if invocation_dir.exists():
            shutil.rmtree(invocation_dir)


if __name__ == "__main__":
    raise SystemExit(main())
