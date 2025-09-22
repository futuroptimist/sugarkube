#!/usr/bin/env python3
"""Automate SSD cloning using the existing ssd_clone.py helper."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

SCRIPT_ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ssd_clone_module", SCRIPT_ROOT / "ssd_clone.py")
ssd_clone = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ssd_clone)  # type: ignore[attr-defined]

NOTIFIER_SCRIPT = SCRIPT_ROOT / "sugarkube_teams.py"

DONE_FILE = ssd_clone.DONE_FILE
STATE_FILE = ssd_clone.STATE_FILE
STATE_DIR = ssd_clone.STATE_DIR
CLONE_HELPER = SCRIPT_ROOT / "ssd_clone.py"
POLL_INTERVAL = int(os.environ.get("SUGARKUBE_SSD_CLONE_POLL_SECS", "10"))
MAX_WAIT = int(os.environ.get("SUGARKUBE_SSD_CLONE_WAIT_SECS", "900"))
EXTRA_ARGS = os.environ.get("SUGARKUBE_SSD_CLONE_EXTRA_ARGS", "")
AUTO_TARGET = os.environ.get(ssd_clone.ENV_TARGET)
LOG_PREFIX = "[ssd-clone-service]"


def _teams_notifications_enabled() -> bool:
    if os.environ.get("SUGARKUBE_TEAMS_WEBHOOK_URL"):
        return True
    matrix_keys = (
        "SUGARKUBE_MATRIX_HOMESERVER",
        "SUGARKUBE_MATRIX_ROOM",
        "SUGARKUBE_MATRIX_ACCESS_TOKEN",
    )
    return all(os.environ.get(key) for key in matrix_keys)


def _notify(event: str, status: str, summary: str, metadata: Optional[dict] = None) -> bool:
    if not NOTIFIER_SCRIPT.exists():
        return False
    if not _teams_notifications_enabled():
        return False

    command = [
        sys.executable or "python3",
        str(NOTIFIER_SCRIPT),
        "--event",
        event,
        "--status",
        status,
        "--summary",
        summary,
    ]
    if metadata:
        command.extend(["--metadata", json.dumps(metadata, sort_keys=True, separators=(",", ":"))])

    process = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )
    if process.returncode != 0:
        stderr = process.stderr.strip()
        if stderr:
            log(f"notification helper failed: {stderr}")
        else:
            log(f"notification helper exited with status {process.returncode}")
        return False
    return True


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", flush=True)


def ensure_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("ssd_clone_service.py must run as root.")


def pick_target() -> Optional[str]:
    if AUTO_TARGET:
        path = Path(AUTO_TARGET)
        if path.exists():
            return AUTO_TARGET
        log(f"Environment target {AUTO_TARGET} missing; waiting for the device to appear.")
        return None
    try:
        return ssd_clone.auto_select_target()
    except SystemExit as error:
        log(str(error))
        return None


def run_clone(target: str) -> int:
    command = [str(CLONE_HELPER), "--target", target, "--resume"]
    if EXTRA_ARGS:
        command.extend(shlex.split(EXTRA_ARGS))
    log(f"Invoking {shlex.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode == 0:
        log("SSD clone completed successfully.")
    else:
        log(f"SSD clone helper exited with status {result.returncode}.")
    return result.returncode


def main() -> None:
    ensure_root()
    hostname = socket.gethostname()
    if DONE_FILE.exists():
        log("Clone already marked complete; exiting.")
        _notify(
            "ssd-clone",
            "info",
            f"SSD clone previously completed on {hostname}",
            {"hostname": hostname},
        )
        return
    if not CLONE_HELPER.exists():
        raise SystemExit("/opt/sugarkube/ssd_clone.py not found; aborting.")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    elapsed = 0
    target: Optional[str] = None
    while elapsed <= MAX_WAIT:
        target = pick_target()
        if target:
            break
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    if not target:
        log(
            "Timed out waiting for an SSD. Insert a target disk or set "
            "SUGARKUBE_SSD_CLONE_TARGET before restarting the service."
        )
        _notify(
            "ssd-clone",
            "warning",
            f"No SSD detected on {hostname}; clone paused",
            {"hostname": hostname},
        )
        raise SystemExit(0)
    metadata = {
        "hostname": hostname,
        "target": target,
        "resume_state": STATE_FILE.exists(),
        "auto_target": bool(AUTO_TARGET),
    }
    _notify(
        "ssd-clone",
        "started",
        f"Cloning SD card to {target}",
        metadata,
    )
    returncode = run_clone(target)
    metadata["returncode"] = returncode
    if returncode != 0 and not STATE_FILE.exists():
        _notify(
            "ssd-clone",
            "failure",
            f"SSD clone helper exited with status {returncode}",
            metadata,
        )
        raise SystemExit(returncode)
    if DONE_FILE.exists():
        log("Clone marker present; nothing else to do.")
        _notify(
            "ssd-clone",
            "success",
            f"SSD clone completed on {hostname}",
            metadata,
        )
        return
    if returncode != 0:
        _notify(
            "ssd-clone",
            "failure",
            f"SSD clone exited with status {returncode}",
            metadata,
        )
    else:
        _notify(
            "ssd-clone",
            "success",
            f"SSD clone completed on {hostname}",
            metadata,
        )
    raise SystemExit(returncode)


if __name__ == "__main__":
    main()
