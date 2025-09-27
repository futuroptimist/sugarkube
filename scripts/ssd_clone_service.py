#!/usr/bin/env python3
"""Automate SSD cloning using the existing ssd_clone.py helper."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - optional dependency during upgrades
    from sugarkube_teams import TeamsNotificationError, TeamsNotifier
except Exception:  # pylint: disable=broad-except
    TeamsNotifier = None  # type: ignore[assignment]
    TeamsNotificationError = RuntimeError  # type: ignore[assignment]

SCRIPT_ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ssd_clone_module", SCRIPT_ROOT / "ssd_clone.py")
ssd_clone = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ssd_clone)  # type: ignore[attr-defined]

DONE_FILE = ssd_clone.DONE_FILE
STATE_FILE = ssd_clone.STATE_FILE
STATE_DIR = ssd_clone.STATE_DIR
CLONE_HELPER = SCRIPT_ROOT / "ssd_clone.py"
POLL_INTERVAL = int(os.environ.get("SUGARKUBE_SSD_CLONE_POLL_SECS", "10"))
MAX_WAIT = int(os.environ.get("SUGARKUBE_SSD_CLONE_WAIT_SECS", "900"))
EXTRA_ARGS = os.environ.get(ssd_clone.ENV_EXTRA_ARGS, "")
AUTO_TARGET = os.environ.get(ssd_clone.ENV_TARGET)
LOG_PREFIX = "[ssd-clone-service]"


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", flush=True)


def notify(event: str, status: str, lines: list[str], fields: dict[str, str]) -> None:
    if TeamsNotifier is None:
        return
    try:
        notifier = TeamsNotifier.from_env()
    except TeamsNotificationError as exc:  # pragma: no cover - optional path
        log(f"teams webhook misconfigured: {exc}")
        return
    if not notifier.enabled:
        return
    try:
        notifier.notify(event=event, status=status, lines=lines, fields=fields)
    except TeamsNotificationError as exc:  # pragma: no cover - network path
        log(f"teams webhook notification failed: {exc}")


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
        log("Honoring %s=%s via helper invocation" % (ssd_clone.ENV_EXTRA_ARGS, EXTRA_ARGS))
    log(f"Invoking {shlex.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode == 0:
        log("SSD clone completed successfully.")
    else:
        log(f"SSD clone helper exited with status {result.returncode}.")
    return result.returncode


def main() -> None:
    ensure_root()
    if DONE_FILE.exists():
        log("Clone already marked complete; exiting.")
        return
    if not CLONE_HELPER.exists():
        raise SystemExit("/opt/sugarkube/ssd_clone.py not found; aborting.")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    notify(
        "ssd-clone",
        "starting",
        [
            f"State file: {STATE_FILE}",
            f"Done marker: {DONE_FILE}",
            f"Auto target env: {AUTO_TARGET or 'auto-detect'}",
        ],
        {},
    )

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
        notify(
            "ssd-clone",
            "failed",
            ["No target disk detected before timeout."],
            {"State file": str(STATE_FILE)},
        )
        raise SystemExit(0)
    notify(
        "ssd-clone",
        "info",
        [f"Target disk: {target}", f"Resume state exists: {STATE_FILE.exists()}"],
        {},
    )
    returncode = run_clone(target)
    state_exists = STATE_FILE.exists()
    done_exists = DONE_FILE.exists()
    if done_exists:
        log("Clone marker present; nothing else to do.")

    fields = {
        "Target": target,
        "State file": str(STATE_FILE),
        "Done marker": str(DONE_FILE),
    }
    if state_exists:
        try:
            state_data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover - best effort
            state_data = {}
        completed = state_data.get("completed", {})
        if isinstance(completed, dict):
            steps = [name for name, done in completed.items() if done]
            if steps:
                fields["Completed steps"] = ", ".join(sorted(steps))

    final_status = "success" if returncode == 0 and done_exists else "failed"
    notify(
        "ssd-clone",
        final_status,
        [
            f"Target disk: {target}",
            f"Return code: {returncode}",
            f"State file present: {state_exists}",
            f"Done marker present: {done_exists}",
        ],
        fields,
    )
    if returncode != 0 and not state_exists:
        raise SystemExit(returncode)
    if done_exists:
        return
    raise SystemExit(returncode)


if __name__ == "__main__":  # pragma: no cover
    main()
