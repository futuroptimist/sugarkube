#!/usr/bin/env python3
"""Collect Pi support bundles over SSH for CI and incident response."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

DEFAULT_OUTPUT_DIR = Path.home() / "sugarkube" / "support-bundles"
DEFAULT_USER = "pi"
DEFAULT_PORT = 22
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_COMMAND_TIMEOUT = 120
DEFAULT_SINCE = "12 hours ago"


@dataclass
class RemoteCommand:
    """Definition for a remote command collected in the support bundle."""

    path: Path
    command: str
    description: str
    binary: bool = False


@dataclass
class CommandResult:
    """Metadata recorded for each captured command."""

    path: str
    command: str
    description: str
    returncode: int
    stderr: str
    bytes_written: int
    note: str | None = None


@dataclass
class CommandCapture:
    """Pair command metadata with the captured data payload."""

    result: CommandResult
    data: bytes


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Connect to Raspberry Pis over SSH, gather Kubernetes/systemd/Compose diagnostics, "
            "and package them into timestamped support bundles."
        )
    )
    parser.add_argument(
        "hosts",
        nargs="+",
        help=(
            "Hostname or IP address of the Pi to inspect. Accept multiple hosts separated by "
            "spaces or newlines."
        ),
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help=f"SSH user. Defaults to '{DEFAULT_USER}'.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"SSH port. Defaults to {DEFAULT_PORT}.",
    )
    parser.add_argument(
        "--identity",
        help="Path to the private key passed to ssh -i.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=DEFAULT_CONNECT_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout (in seconds) for establishing each SSH connection. "
            f"Defaults to {DEFAULT_CONNECT_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout (in seconds) for each remote command execution. "
            f"Defaults to {DEFAULT_COMMAND_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Directory where support bundles are written. "
            "Defaults to ~/sugarkube/support-bundles."
        ),
    )
    parser.add_argument(
        "--since",
        default=DEFAULT_SINCE,
        help=(
            "Time window passed to journalctl when collecting logs. "
            "Quote values with spaces. Defaults to '12 hours ago'."
        ),
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Additional -o options passed directly to ssh (repeatable).",
    )
    parser.add_argument(
        "--skip-first-boot-report",
        action="store_true",
        help="Skip archiving /boot/first-boot-report when absent or unnecessary.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any remote command fails. Default is to succeed with warnings.",
    )
    return parser.parse_args(argv)


def sanitize_host(host: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in host)


def build_remote_commands(since: str) -> List[RemoteCommand]:
    since_q = shlex.quote(since)
    commands: List[RemoteCommand] = [
        RemoteCommand(
            path=Path("kubernetes/nodes.txt"),
            command="sudo kubectl get nodes -o wide",
            description="Kubernetes node status",
        ),
        RemoteCommand(
            path=Path("kubernetes/pods.txt"),
            command="sudo kubectl get pods --all-namespaces -o wide",
            description="All pods across namespaces",
        ),
        RemoteCommand(
            path=Path("kubernetes/events.yaml"),
            command=(
                "sudo kubectl get events --all-namespaces "
                "--sort-by=.metadata.creationTimestamp -o yaml"
            ),
            description="Cluster events sorted by timestamp",
        ),
        RemoteCommand(
            path=Path("kubernetes/services.txt"),
            command="sudo kubectl get svc --all-namespaces -o wide",
            description="Service overview",
        ),
        RemoteCommand(
            path=Path("kubernetes/describe-nodes.txt"),
            command="sudo kubectl describe nodes",
            description="Detailed node descriptions",
        ),
        RemoteCommand(
            path=Path("kubernetes/version.yaml"),
            command="sudo kubectl version --output=yaml",
            description="Kubectl client and server versions",
        ),
        RemoteCommand(
            path=Path("helm/list.yaml"),
            command="sudo helm list --all-namespaces --output yaml",
            description="Installed Helm releases",
        ),
        RemoteCommand(
            path=Path("compose/projects-compose.log"),
            command=(
                "cd /opt/projects 2>/dev/null && "
                "sudo docker compose -f docker-compose.yml logs --no-color --tail=500"
            ),
            description="docker compose logs for token.place and dspace",
        ),
        RemoteCommand(
            path=Path("systemd/blame.txt"),
            command="sudo systemd-analyze blame",
            description="Systemd unit startup timings",
        ),
        RemoteCommand(
            path=Path("systemd/critical-chain.txt"),
            command="sudo systemd-analyze critical-chain",
            description="Critical path analysis",
        ),
        RemoteCommand(
            path=Path("systemd/failed-units.txt"),
            command="sudo systemctl --failed",
            description="Failed systemd units",
        ),
        RemoteCommand(
            path=Path("journal/k3s.log"),
            command=("sudo journalctl --no-pager --output=short-iso " f"--since {since_q} -u k3s"),
            description="k3s journal excerpt",
        ),
        RemoteCommand(
            path=Path("journal/projects-compose.log"),
            command=(
                "sudo journalctl --no-pager --output=short-iso "
                f"--since {since_q} -u projects-compose.service"
            ),
            description="projects-compose.service journal excerpt",
        ),
        RemoteCommand(
            path=Path("journal/self-heal.log"),
            command=(
                "sudo journalctl --no-pager --output=short-iso "
                f"--since {since_q} -u 'sugarkube-self-heal@*'"
            ),
            description="Self-heal journal excerpt",
        ),
        RemoteCommand(
            path=Path("journal/cloud-init.log"),
            command=(
                "sudo journalctl --no-pager --output=short-iso "
                f"--since {since_q} -u cloud-init -u cloud-final -u cloud-config"
            ),
            description="cloud-init journal excerpt",
        ),
        RemoteCommand(
            path=Path("system/df.txt"),
            command="df -h",
            description="Filesystem usage",
        ),
        RemoteCommand(
            path=Path("system/free.txt"),
            command="free -h",
            description="Memory usage",
        ),
        RemoteCommand(
            path=Path("system/uptime.txt"),
            command="uptime",
            description="Uptime and load average",
        ),
    ]
    return commands


class SupportBundleCollector:
    """Collect support bundles from Pi hosts."""

    def __init__(
        self,
        args: argparse.Namespace,
        runner: callable | None = None,
        now_fn: callable | None = None,
    ) -> None:
        self.args = args
        self.runner = runner or subprocess.run
        self.now_fn = now_fn or dt.datetime.utcnow
        self.failures: List[str] = []

    def collect(self) -> bool:
        output_root = Path(self.args.output_dir).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)
        commands = build_remote_commands(self.args.since)
        overall_success = True

        for host in self.args.hosts:
            host_success = self._collect_for_host(host, output_root, commands)
            if not host_success:
                overall_success = False
                message = f"[{host}] one or more commands returned a non-zero exit code"
                self.failures.append(message)
                print(message, file=sys.stderr)

        return overall_success

    def _collect_for_host(
        self,
        host: str,
        output_root: Path,
        commands: Iterable[RemoteCommand],
    ) -> bool:
        safe_host = sanitize_host(host)
        timestamp = self.now_fn().replace(microsecond=0).isoformat().replace(":", "")
        host_dir = output_root / f"{timestamp}-{safe_host}"
        host_dir.mkdir(parents=True, exist_ok=True)
        metadata: List[CommandResult] = []
        host_success = True

        for remote in commands:
            capture = self._run_remote(host, remote)
            self._write_capture(host_dir / remote.path, capture)
            metadata.append(capture.result)
            if capture.result.returncode != 0:
                host_success = False
            print(
                f"[{host}] captured {remote.path} (exit {capture.result.returncode}, "
                f"{capture.result.bytes_written} bytes)",
            )

        if not self.args.skip_first_boot_report:
            fb_capture = self._capture_first_boot_report(host)
            boot_archive = host_dir / Path("boot/first-boot-report.tar.gz")
            self._write_capture(
                boot_archive,
                fb_capture,
                allow_placeholder=False,
            )
            metadata.append(fb_capture.result)
            if fb_capture.result.returncode != 0:
                host_success = False
            print(
                f"[{host}] captured {boot_archive.relative_to(host_dir)} "
                f"(exit {fb_capture.result.returncode}, {fb_capture.result.bytes_written} bytes)",
            )

        collected_at = self.now_fn().isoformat() + "Z"
        metadata_path = host_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "host": host,
                    "collected_at": collected_at,
                    "commands": [asdict(result) for result in metadata],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        archive_path = shutil.make_archive(
            str(host_dir), "gztar", root_dir=host_dir.parent, base_dir=host_dir.name
        )
        print(f"[{host}] wrote archive {archive_path}")
        return host_success

    def _run_remote(self, host: str, remote: RemoteCommand) -> CommandCapture:
        ssh_command = self._build_ssh_command(host)
        remote_command = f"set -o pipefail; {remote.command}"
        try:
            completed = self.runner(  # type: ignore[misc]
                [*ssh_command, remote_command],
                capture_output=True,
                text=not remote.binary,
                timeout=self.args.command_timeout,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - defensive
            stderr = str(exc)
            note = "timeout"
            stdout = exc.stdout or (b"" if remote.binary else "")
            if remote.binary and isinstance(stdout, (bytes, bytearray)):
                data = bytes(stdout)
            else:
                if isinstance(stdout, (bytes, bytearray)):
                    decoded = stdout.decode("utf-8", "replace")
                else:
                    decoded = "" if stdout is None else str(stdout)
                data = decoded.encode("utf-8") if decoded else b""
            result = CommandResult(
                path=str(remote.path),
                command=remote.command,
                description=remote.description,
                returncode=-1,
                stderr=stderr,
                bytes_written=0,
                note=note,
            )
            return CommandCapture(result=result, data=data)

        stderr_text = completed.stderr
        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode("utf-8", "replace")
        elif stderr_text is None:
            stderr_text = ""

        note = None
        if completed.returncode != 0:
            note = f"exit-{completed.returncode}"

        if remote.binary:
            stdout_value = completed.stdout
            if isinstance(stdout_value, (bytes, bytearray)):
                data = bytes(stdout_value)
            else:
                data = b""
        else:
            stdout_text = completed.stdout if isinstance(completed.stdout, str) else ""
            if completed.returncode != 0 and stderr_text:
                stripped_stdout = stdout_text.rstrip("\n")
                combined = f"{stripped_stdout}\n\n[stderr]\n{stderr_text}".rstrip("\n") + "\n"
            else:
                combined = stdout_text
            data = combined.encode("utf-8")

        result = CommandResult(
            path=str(remote.path),
            command=remote.command,
            description=remote.description,
            returncode=completed.returncode,
            stderr=stderr_text,
            bytes_written=0,
            note=note,
        )
        return CommandCapture(result=result, data=data)

    def _capture_first_boot_report(self, host: str) -> CommandCapture:
        remote = RemoteCommand(
            path=Path("boot/first-boot-report.tar.gz"),
            command=(
                "if [ -d /boot/first-boot-report ]; then "
                "sudo tar -C /boot -czf - first-boot-report; "
                "else echo 'first-boot-report directory missing' >&2; fi"
            ),
            description="Archive of /boot/first-boot-report",
            binary=True,
        )
        return self._run_remote(host, remote)

    def _write_capture(
        self,
        path: Path,
        capture: CommandCapture,
        *,
        allow_placeholder: bool = True,
    ) -> None:
        data = capture.data
        if not data:
            self._append_note(capture.result, "no-output")
            if not allow_placeholder:
                capture.result.bytes_written = 0
                return
            data = b"(no output captured)\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        capture.result.bytes_written = len(data)

    def _append_note(self, result: CommandResult, message: str) -> None:
        if result.note:
            if message not in result.note:
                result.note = f"{result.note}; {message}"
        else:
            result.note = message

    def _build_ssh_command(self, host: str) -> List[str]:
        base: List[str] = [
            "ssh",
            "-p",
            str(self.args.port),
            "-o",
            f"ConnectTimeout={self.args.connect_timeout}",
            "-o",
            "BatchMode=yes",
        ]
        for option in self.args.ssh_option:
            base.extend(["-o", option])
        if self.args.identity:
            base.extend(["-i", self.args.identity])
        target = host if "@" in host else f"{self.args.user}@{host}"
        base.append(target)
        base.extend(["bash", "-lc"])
        return base


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    collector = SupportBundleCollector(args)
    success = collector.collect()
    if not success and args.strict:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
