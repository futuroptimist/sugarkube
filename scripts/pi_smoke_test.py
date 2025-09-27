#!/usr/bin/env python3
"""SSH-based smoke test harness for freshly provisioned Pi nodes."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

DEFAULT_VERIFIER_PATH = "/usr/local/sbin/pi_node_verifier.sh"
DEFAULT_USER = "pi"
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_COMMAND_TIMEOUT = 120
DEFAULT_REBOOT_TIMEOUT = 600
DEFAULT_POLL_INTERVAL = 5


class SmokeTestError(RuntimeError):
    """Raised when the smoke test fails or cannot reach a node."""


@dataclass
class SmokeTestResult:
    host: str
    checks: List[Dict[str, str]]
    passes: int
    total: int
    failures: List[Dict[str, str]]

    @property
    def success(self) -> bool:
        return not self.failures


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Connect to each host over SSH, run pi_node_verifier.sh, and report pass/fail status."
        )
    )
    parser.add_argument(
        "hosts",
        nargs="*",
        metavar="HOST",
        help=(
            "Hostname or IP address of the Pi to verify. "
            "Accept multiple values to test several nodes in sequence."
        ),
    )
    parser.add_argument(
        "--host",
        dest="hosts_from_flag",
        action="append",
        metavar="HOST",
        help="Add a host to the verification list (repeatable).",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help=f"SSH user. Defaults to '{DEFAULT_USER}'.",
    )
    parser.add_argument(
        "--identity",
        help="Path to a private key passed to ssh -i.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="SSH port. Defaults to 22.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=DEFAULT_CONNECT_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout (in seconds) for establishing each SSH connection."
            f" Defaults to {DEFAULT_CONNECT_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout (in seconds) for pi_node_verifier.sh execution."
            f" Defaults to {DEFAULT_COMMAND_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--verifier-path",
        default=DEFAULT_VERIFIER_PATH,
        help=("Remote path to pi_node_verifier.sh." f" Defaults to {DEFAULT_VERIFIER_PATH}."),
    )
    parser.add_argument(
        "--token-place-url",
        help="Override TOKEN_PLACE_HEALTH_URL when running the verifier.",
    )
    parser.add_argument(
        "--dspace-url",
        help="Override DSPACE_HEALTH_URL when running the verifier.",
    )
    parser.add_argument(
        "--skip-token-place",
        action="store_true",
        help="Skip the token.place health probe (sets TOKEN_PLACE_HEALTH_URL=skip).",
    )
    parser.add_argument(
        "--skip-dspace",
        action="store_true",
        help="Skip the dspace health probe (sets DSPACE_HEALTH_URL=skip).",
    )
    parser.add_argument(
        "--no-sudo",
        action="store_true",
        help="Run the verifier without sudo (assumes the remote user has access).",
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Additional -o options passed directly to ssh (repeatable).",
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        help="Reboot after the first successful verifier run and repeat the checks.",
    )
    parser.add_argument(
        "--reboot-timeout",
        type=int,
        default=DEFAULT_REBOOT_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Maximum time (in seconds) to wait for a host to reconnect after reboot."
            f" Defaults to {DEFAULT_REBOOT_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        metavar="SECONDS",
        help=(
            "Interval (in seconds) between SSH reachability probes while waiting for a reboot."
            f" Defaults to {DEFAULT_POLL_INTERVAL}."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON summary in addition to human-readable output.",
    )
    args = parser.parse_args(argv)
    hosts: List[str] = []
    if args.hosts:
        hosts.extend(args.hosts)
    if args.hosts_from_flag:
        hosts.extend(args.hosts_from_flag)

    if not hosts:
        parser.error("provide at least one host via positional arguments or --host")

    args.hosts = hosts
    delattr(args, "hosts_from_flag")
    return args


def parse_verifier_output(output: str) -> List[Dict[str, str]]:
    text = output.strip()
    if not text:
        raise SmokeTestError("verifier produced no output")

    last_line = text.splitlines()[-1]
    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise SmokeTestError("failed to parse verifier JSON output") from exc

    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise SmokeTestError("verifier JSON missing 'checks' array")

    normalized: List[Dict[str, str]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        status = str(item.get("status", ""))
        normalized.append({"name": name, "status": status})

    if not normalized:
        raise SmokeTestError("verifier JSON did not contain any checks")

    return normalized


def summarise_checks(checks: Iterable[Dict[str, str]]) -> SmokeTestResult:
    check_list = list(checks)
    failures = [c for c in check_list if c.get("status") not in {"pass", "skip"}]
    passes = sum(1 for c in check_list if c.get("status") == "pass")
    return SmokeTestResult(
        host="",
        checks=check_list,
        passes=passes,
        total=len(check_list),
        failures=failures,
    )


def build_env(args: argparse.Namespace) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if args.skip_token_place:
        env["TOKEN_PLACE_HEALTH_URL"] = "skip"
    elif args.token_place_url:
        env["TOKEN_PLACE_HEALTH_URL"] = args.token_place_url

    if args.skip_dspace:
        env["DSPACE_HEALTH_URL"] = "skip"
    elif args.dspace_url:
        env["DSPACE_HEALTH_URL"] = args.dspace_url

    return env


def build_ssh_command(host: str, args: argparse.Namespace, remote_command: str) -> List[str]:
    destination = f"{args.user}@{host}" if args.user else host
    command = [
        "ssh",
        "-p",
        str(args.port),
        "-o",
        f"ConnectTimeout={args.connect_timeout}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
    ]
    for opt in args.ssh_option:
        command.extend(["-o", opt])
    if args.identity:
        command.extend(["-i", args.identity])
    command.append(destination)
    command.append(remote_command)
    return command


def run_ssh(
    host: str,
    args: argparse.Namespace,
    remote_command: str,
    *,
    timeout: int,
) -> subprocess.CompletedProcess:
    cmd = build_ssh_command(host, args, remote_command)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_verifier(host: str, args: argparse.Namespace) -> SmokeTestResult:
    env = build_env(args)
    env_parts = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    verifier_cmd = [args.verifier_path, "--json", "--no-log"]
    if args.no_sudo:
        command = shlex.join(verifier_cmd)
    else:
        command = shlex.join(["sudo", "-n", *verifier_cmd])
    remote_command = " ".join(env_parts + [command]) if env_parts else command

    try:
        result = run_ssh(host, args, remote_command, timeout=args.command_timeout)
    except subprocess.TimeoutExpired as exc:
        raise SmokeTestError(f"timed out waiting for verifier on {host}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise SmokeTestError(
            f"verifier returned {result.returncode} on {host}: {stderr or 'no stderr captured'}"
        )

    checks = parse_verifier_output(result.stdout)
    summary = summarise_checks(checks)
    summary.host = host
    return summary


def wait_for_ssh(host: str, args: argparse.Namespace, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = run_ssh(host, args, "true", timeout=args.connect_timeout)
        except subprocess.TimeoutExpired:
            result = None
        if result and result.returncode == 0:
            return
        time.sleep(args.poll_interval)
    raise SmokeTestError(f"host {host} did not become reachable within {timeout} seconds")


def trigger_reboot(host: str, args: argparse.Namespace) -> None:
    reboot_cmd = "sudo -n reboot" if not args.no_sudo else "reboot"
    result = run_ssh(host, args, reboot_cmd, timeout=args.connect_timeout)
    if result.returncode not in (0, 255):
        raise SmokeTestError(
            f"reboot command returned {result.returncode} on {host}:"
            f" {result.stderr.strip() or 'no stderr captured'}"
        )


def format_summary(result: SmokeTestResult) -> str:
    status = "PASS" if result.success else "FAIL"
    return (
        f"[{result.host}] {status}: {result.passes}/{result.total} checks passed"
        f" ({len(result.failures)} failing)."
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    failures: List[SmokeTestResult] = []
    json_payload = []

    for host in args.hosts:
        try:
            initial = run_verifier(host, args)
        except SmokeTestError as exc:
            message = str(exc)
            print(f"[{host}] ERROR: {message}", file=sys.stderr)
            failures.append(SmokeTestResult(host, [], 0, 0, []))
            json_payload.append({"host": host, "error": message})
            continue

        print(format_summary(initial))
        if not initial.success:
            failures.append(initial)
        json_payload.append(
            {
                "host": host,
                "passes": initial.passes,
                "total": initial.total,
                "failures": initial.failures,
            }
        )

        if args.reboot and initial.success:
            print(f"[{host}] Rebooting to confirm convergence...")
            try:
                trigger_reboot(host, args)
            except SmokeTestError as exc:
                message = str(exc)
                print(f"[{host}] ERROR during reboot: {message}", file=sys.stderr)
                failures.append(SmokeTestResult(host, [], 0, 0, []))
                json_payload.append({"host": host, "phase": "reboot", "error": message})
                continue
            time.sleep(args.poll_interval)
            try:
                wait_for_ssh(host, args, args.reboot_timeout)
                post_reboot = run_verifier(host, args)
            except SmokeTestError as exc:
                message = str(exc)
                print(f"[{host}] ERROR after reboot: {message}", file=sys.stderr)
                failures.append(SmokeTestResult(host, [], 0, 0, []))
                json_payload.append({"host": host, "phase": "post-reboot", "error": message})
                continue
            print(f"[{host}] Post-reboot {format_summary(post_reboot)}")
            if not post_reboot.success:
                failures.append(post_reboot)
            json_payload.append(
                {
                    "host": host,
                    "phase": "post-reboot",
                    "passes": post_reboot.passes,
                    "total": post_reboot.total,
                    "failures": post_reboot.failures,
                }
            )

    if args.json:
        print(json.dumps({"results": json_payload}, indent=2))

    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
