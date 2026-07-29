#!/usr/bin/env python3
"""Guarded lifecycle for the staging host-level Healthchecks.io heartbeat."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import socket
import stat
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "clusters/staging/nodes.txt"
SERVICE = "sugarkube-healthcheck-heartbeat.service"
TIMER = "sugarkube-healthcheck-heartbeat.timer"
URL_RE = re.compile(
    r"https://hc-ping\.com/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)


def root_path(path: str) -> Path:
    root = os.environ.get("SUGARKUBE_HEARTBEAT_TEST_ROOT")
    return Path(root) / path.lstrip("/") if root else Path(path)


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, check=check, text=True, capture_output=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"ERROR: required tool {args[0]!r} is unavailable") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ERROR: sanitized command failed: {args[0]}") from exc


def guard(environment: str) -> str:
    if environment != "staging":
        raise SystemExit(
            "ERROR: this operation requires explicit env=staging; production and unknown environments are refused"
        )
    hostname = (
        os.environ.get("SUGARKUBE_HEARTBEAT_TEST_HOSTNAME")
        or socket.gethostname().split(".")[0].lower()
    )
    allowed = {
        line.strip()
        for line in INVENTORY.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    if hostname not in allowed:
        raise SystemExit(
            f"ERROR: hostname {hostname!r} is not in the canonical staging node inventory"
        )
    return hostname


def require_root() -> None:
    if not os.environ.get("SUGARKUBE_HEARTBEAT_TEST_ROOT") and os.geteuid() != 0:
        raise SystemExit(
            "ERROR: lifecycle mutations must run as root (use the Just recipe)"
        )


def read_secret() -> bytes:
    if os.environ.get("SUGARKUBE_HEALTHCHECK_PING_URL"):
        raise SystemExit(
            "ERROR: exported credentials are refused; use the silent controlling-terminal prompt"
        )
    tty_name = (
        os.environ.get("SUGARKUBE_HEARTBEAT_TEST_TTY")
        if os.environ.get("SUGARKUBE_HEARTBEAT_TEST_ROOT")
        else "/dev/tty"
    )
    if not tty_name:
        raise SystemExit("ERROR: a controlling terminal is required")
    try:
        with open(tty_name, "r+", encoding="ascii") as tty:
            value = getpass.getpass("Healthchecks.io ping URL (hidden): ", stream=tty)
    except (OSError, EOFError) as exc:
        raise SystemExit(
            "ERROR: unable to read a hidden credential from the controlling terminal"
        ) from exc
    if URL_RE.fullmatch(value) is None:
        raise SystemExit(
            "ERROR: credential must be one canonical HTTPS hc-ping.com UUID ping URL (no suffix, query, or fragment)"
        )
    return value.encode("ascii") + b"\n"


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, candidate = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(candidate, path)
        if not os.environ.get("SUGARKUBE_HEARTBEAT_TEST_ROOT"):
            os.chown(path, 0, 0)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(candidate)
        except FileNotFoundError:
            pass


def install(environment: str) -> None:
    host = guard(environment)
    require_root()
    secret = read_secret()
    atomic_write(root_path("/etc/sugarkube/healthcheck-ping-url"), secret, 0o600)
    secret = b""
    assets = (
        (
            "/usr/local/libexec/sugarkube-healthcheck-heartbeat",
            "scripts/sugarkube_healthcheck_heartbeat.py",
            0o755,
        ),
        (f"/etc/systemd/system/{SERVICE}", f"scripts/systemd/{SERVICE}", 0o644),
        (f"/etc/systemd/system/{TIMER}", f"scripts/systemd/{TIMER}", 0o644),
    )
    for target, source, mode in assets:
        atomic_write(root_path(target), (REPO / source).read_bytes(), mode)
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", TIMER)
    run("systemctl", "start", TIMER)
    print(
        f"Installed staging node heartbeat on {host}; credential stored with mode 0600"
    )


def file_fact(path: Path, mode: int) -> str:
    try:
        info = path.stat()
        correct = stat.S_IMODE(info.st_mode) == mode and (
            bool(os.environ.get("SUGARKUBE_HEARTBEAT_TEST_ROOT"))
            or (info.st_uid, info.st_gid) == (0, 0)
        )
        return (
            "present, owner/permissions ok"
            if correct
            else "present, owner/permissions WRONG"
        )
    except FileNotFoundError:
        return "missing"


def status(environment: str) -> None:
    host = guard(environment)
    print(f"Hostname: {host}")
    for label, path, mode in (
        ("Credential", "/etc/sugarkube/healthcheck-ping-url", 0o600),
        ("Service", f"/etc/systemd/system/{SERVICE}", 0o644),
        ("Timer", f"/etc/systemd/system/{TIMER}", 0o644),
        ("Executable", "/usr/local/libexec/sugarkube-healthcheck-heartbeat", 0o755),
    ):
        print(f"{label}: {file_fact(root_path(path), mode)}")
    for label, command in (
        ("Timer enabled", "is-enabled"),
        ("Timer active", "is-active"),
    ):
        result = run("systemctl", command, TIMER, check=False)
        print(f"{label}: {result.stdout.strip() or 'unknown'}")
    result = run(
        "systemctl", "show", SERVICE, "--property=Result", "--value", check=False
    )
    print(f"Last service result: {result.stdout.strip() or 'unknown'}")
    print("Timing: 30 seconds after boot, then every minute (5-second accuracy)")


def verify(environment: str) -> None:
    host = guard(environment)
    require_root()
    if run("systemctl", "is-enabled", TIMER, check=False).returncode != 0:
        raise SystemExit("ERROR: recurring heartbeat timer is not enabled")
    run("systemctl", "start", SERVICE)
    deadline = time.monotonic() + 40
    while (
        time.monotonic() < deadline
        and run("systemctl", "is-active", SERVICE, check=False).stdout.strip()
        == "activating"
    ):
        time.sleep(1)
    result = run(
        "systemctl", "show", SERVICE, "--property=Result", "--value", check=False
    ).stdout.strip()
    if result != "success":
        raise SystemExit(
            "ERROR: heartbeat did not complete successfully within 40 seconds; inspect sanitized unit diagnostics"
        )
    run("systemctl", "start", TIMER)
    print(
        f"Verified one successful heartbeat on {host}; recurring timer remains enabled"
    )


def uninstall(environment: str, confirmation: str) -> None:
    host = guard(environment)
    require_root()
    if confirmation != host:
        raise SystemExit(f"ERROR: destructive uninstall requires --confirm {host}")
    run("systemctl", "disable", "--now", TIMER, check=False)
    for path in (
        f"/etc/systemd/system/{SERVICE}",
        f"/etc/systemd/system/{TIMER}",
        "/usr/local/libexec/sugarkube-healthcheck-heartbeat",
        "/etc/sugarkube/healthcheck-ping-url",
    ):
        root_path(path).unlink(missing_ok=True)
    run("systemctl", "daemon-reload")
    print(
        f"Removed host heartbeat assets and local credential from {host}; remote Healthchecks.io and PagerDuty configuration was not changed"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "status", "verify", "uninstall"))
    parser.add_argument("--env", required=True)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    {"install": install, "status": status, "verify": verify}.get(
        args.action, lambda env: uninstall(env, args.confirm)
    )(args.env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
