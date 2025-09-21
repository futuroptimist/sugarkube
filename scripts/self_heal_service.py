#!/usr/bin/env python3

"""Systemd self-healing helper for sugarkube Pi images.

This helper is invoked by ``sugarkube-self-heal@.service`` when a critical unit
fails (for example ``projects-compose.service`` or ``cloud-final.service``).
It retries automated recovery steps, captures diagnostic logs, and escalates to
maintenance mode after repeated failures.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_STATE_DIR = Path("/var/log/sugarkube/self-heal")
DEFAULT_BOOT_DIR = Path("/boot/first-boot-report/self-heal")
DEFAULT_LOG_DIR = DEFAULT_STATE_DIR
DEFAULT_MAX_ATTEMPTS = 3


_USE_DEFAULT_TIMEOUT = object()


@dataclass
class CommandResult:
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Execute commands with optional test-mode overrides."""

    def __init__(self, logger: "SelfHealLogger") -> None:
        self.logger = logger
        self.test_mode = os.environ.get("SELF_HEAL_TEST_MODE", "0") != "0"
        failures = os.environ.get("SELF_HEAL_TEST_FAILURES", "")
        self.failure_patterns = {
            pattern.strip() for pattern in failures.split(",") if pattern.strip()
        }
        timeout_env = os.environ.get("SELF_HEAL_DEFAULT_TIMEOUT", "").strip()
        self.default_timeout: float | int | None
        if timeout_env:
            try:
                self.default_timeout = float(timeout_env)
            except ValueError:
                self.logger.log(
                    "invalid SELF_HEAL_DEFAULT_TIMEOUT value; falling back to no timeout"
                )
                self.default_timeout = None
        else:
            self.default_timeout = None

    def run(
        self,
        cmd: Iterable[str],
        check: bool = False,
        *,
        timeout: float | int | None | object = _USE_DEFAULT_TIMEOUT,
    ) -> CommandResult:
        args = list(cmd)
        if not args:
            raise ValueError("command must not be empty")

        cmd_str = " ".join(args)
        if self.test_mode:
            result = self._run_test_mode(args, cmd_str)
        else:
            effective_timeout = self.default_timeout if timeout is _USE_DEFAULT_TIMEOUT else timeout
            result = self._run_real(args, effective_timeout)

        self.logger.log(f"ran: {cmd_str} (rc={result.returncode})")
        if result.stdout.strip():
            self.logger.log(f"stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            self.logger.log(f"stderr: {result.stderr.strip()}")

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, args, output=result.stdout, stderr=result.stderr
            )
        return result

    def _run_real(self, args: list[str], timeout: float | int | None) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return CommandResult(args, 124, stdout, stderr)
        return CommandResult(args, completed.returncode, completed.stdout, completed.stderr)

    def _run_test_mode(self, args: list[str], cmd_str: str) -> CommandResult:
        for pattern in self.failure_patterns:
            if pattern and pattern in cmd_str:
                stdout = ""
                stderr = f"forced failure via {pattern}"
                return CommandResult(args, 1, stdout, stderr)

        stdout = ""
        if len(args) >= 3 and args[0] == "systemctl" and args[1] == "is-active":
            stdout = "active\n"
        elif len(args) >= 2 and args[0] == "cloud-init" and args[1] == "status":
            stdout = "status: done\n"
        return CommandResult(args, 0, stdout, "")


class SelfHealLogger:
    """Append structured logs to an on-disk file."""

    def __init__(self, log_file: Path) -> None:
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp} {message}"
        print(line)
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


@dataclass
class SelfHealConfig:
    unit: str
    state_dir: Path
    boot_dir: Path
    log_dir: Path
    max_attempts: int

    @classmethod
    def from_env(cls, unit: str) -> "SelfHealConfig":
        state_dir = Path(os.environ.get("SELF_HEAL_STATE_DIR", str(DEFAULT_STATE_DIR)))
        boot_dir = Path(os.environ.get("SELF_HEAL_BOOT_DIR", str(DEFAULT_BOOT_DIR)))
        log_dir = Path(os.environ.get("SELF_HEAL_LOG_DIR", str(DEFAULT_LOG_DIR)))
        max_attempts = int(os.environ.get("SELF_HEAL_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))
        return cls(
            unit=unit,
            state_dir=state_dir,
            boot_dir=boot_dir,
            log_dir=log_dir,
            max_attempts=max_attempts,
        )

    @property
    def unit_slug(self) -> str:
        return self.unit.replace("/", "-")

    @property
    def state_file(self) -> Path:
        return self.state_dir / f"{self.unit_slug}.json"

    @property
    def log_file(self) -> Path:
        return self.log_dir / f"{self.unit_slug}.log"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"attempts": 0, "updated": None}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {"attempts": 0, "updated": None}


def save_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def capture_logs(runner: CommandRunner, logger: SelfHealLogger, unit: str) -> str:
    journal_output = ""
    if shutil.which("journalctl") or runner.test_mode:
        result = runner.run(["journalctl", "-u", unit, "--no-pager", "-n", "200"])
        journal_output = result.stdout
    else:
        logger.log("journalctl not available; skipping unit logs")
    return journal_output


def write_boot_summary(
    config: SelfHealConfig,
    logger: SelfHealLogger,
    journal: str,
    reason: str,
) -> Path | None:
    try:
        config.boot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.log(f"failed to create boot directory {config.boot_dir}: {exc}")
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_path = config.boot_dir / f"{config.unit_slug}-maintenance-{timestamp}.md"
    try:
        with summary_path.open("w", encoding="utf-8") as handle:
            handle.write(f"# Self-heal escalation for {config.unit}\n\n")
            handle.write(f"- Timestamp: {datetime.now(timezone.utc).isoformat()}\n")
            handle.write(f"- Reason: {reason}\n")
            handle.write(f"- Attempts: escalated after {config.max_attempts} failures\n")
            handle.write(
                "- Next steps: connect via console, review logs below, and re-run the verifier.\n\n"
            )
            if journal.strip():
                handle.write("## Recent journalctl output\n\n`````\n")
                handle.write(journal.strip())
                handle.write("\n`````\n")
            else:
                handle.write("No journal output was captured.\n")
    except OSError as exc:
        logger.log(f"failed to write boot summary {summary_path}: {exc}")
        return None

    logger.log(f"wrote escalation summary to {summary_path}")
    return summary_path


def enter_maintenance(runner: CommandRunner, logger: SelfHealLogger) -> None:
    logger.log("entering maintenance mode via rescue.target")
    if runner.test_mode:
        logger.log("test mode enabled; skipping systemctl isolate rescue.target")
        return
    runner.run(["systemctl", "isolate", "rescue.target"])


def handle_projects_compose(
    config: SelfHealConfig,
    runner: CommandRunner,
    logger: SelfHealLogger,
) -> bool:
    compose_file = "/opt/projects/docker-compose.yml"
    if not Path(compose_file).exists() and not runner.test_mode:
        logger.log(f"compose file missing: {compose_file}")
        return False

    if shutil.which("docker") or runner.test_mode:
        runner.run(["docker", "compose", "-f", compose_file, "pull"])
        runner.run(["docker", "compose", "-f", compose_file, "up", "-d"])
    else:
        logger.log("docker not available; cannot refresh containers")
        return False

    if shutil.which("systemctl") or runner.test_mode:
        runner.run(["systemctl", "reset-failed", config.unit])
        runner.run(["systemctl", "restart", config.unit])
        status = runner.run(["systemctl", "is-active", config.unit])
        return status.returncode == 0 and "active" in status.stdout.lower()

    logger.log("systemctl not available; cannot restart compose unit")
    return False


def handle_cloud_init(
    config: SelfHealConfig,
    runner: CommandRunner,
    logger: SelfHealLogger,
) -> bool:
    if not shutil.which("cloud-init") and not runner.test_mode:
        logger.log("cloud-init missing; cannot clean state")
        return False

    runner.run(["cloud-init", "status", "--long"])
    runner.run(["cloud-init", "clean", "--logs"])

    if shutil.which("systemctl") or runner.test_mode:
        runner.run(["systemctl", "reset-failed", "cloud-init.target"])
        runner.run(["systemctl", "start", "cloud-init.target"])
    else:
        logger.log("systemctl not available; skipping cloud-init target restart")
        return False

    status = runner.run(["cloud-init", "status", "--wait", "--long"])
    if status.returncode != 0:
        return False
    return "status: done" in status.stdout.lower()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sugarkube self-heal helper")
    parser.add_argument("--unit", required=True, help="systemd unit that triggered self-heal")
    parser.add_argument("--reason", default="unit failure", help="optional failure reason")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = SelfHealConfig.from_env(args.unit)
    logger = SelfHealLogger(config.log_file)
    runner = CommandRunner(logger)

    state = load_state(config.state_file)
    attempts = int(state.get("attempts", 0)) + 1
    state["attempts"] = attempts
    save_state(config.state_file, state)
    logger.log(f"self-heal attempt {attempts}/{config.max_attempts} for {config.unit}")

    success = False
    if args.unit == "projects-compose.service":
        success = handle_projects_compose(config, runner, logger)
    elif args.unit in {"cloud-final.service", "cloud-init.service", "cloud-config.service"}:
        success = handle_cloud_init(config, runner, logger)
    else:
        logger.log(f"no self-heal recipe for {args.unit}")

    if success:
        logger.log(f"recovery succeeded for {config.unit}; resetting attempt counter")
        save_state(config.state_file, {"attempts": 0})
        return 0

    logger.log(f"recovery failed for {config.unit}")
    if attempts >= config.max_attempts:
        journal = capture_logs(runner, logger, config.unit)
        summary = write_boot_summary(config, logger, journal, args.reason)
        if summary is not None:
            logger.log(f"summary available at {summary}")
        enter_maintenance(runner, logger)
    return 1


if __name__ == "__main__":
    sys.exit(main())
