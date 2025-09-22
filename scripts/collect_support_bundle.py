#!/usr/bin/env python3
"""Collect observability and troubleshooting data into a tarball support bundle."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

DEFAULT_REMOTE_USER = "pi"
DEFAULT_REMOTE_PORT = 22
DEFAULT_FIRST_BOOT_REPORT = "/boot/first-boot-report"
DEFAULT_OUTPUT = "support-bundle.tar.gz"


class SupportBundleError(RuntimeError):
    """Raised when the support bundle collection cannot proceed."""


@dataclass
class CommandSpec:
    name: str
    command: Sequence[str]
    description: str
    sudo: bool = True
    optional: bool = True


DEFAULT_COMMANDS: List[CommandSpec] = [
    CommandSpec(
        name="kubectl-events",
        description="Recent Kubernetes events across namespaces",
        command=("kubectl", "get", "events", "-A", "--sort-by=.lastTimestamp"),
    ),
    CommandSpec(
        name="kubectl-pods",
        description="All pods with wide output for debugging scheduling",
        command=("kubectl", "get", "pods", "-A", "-o", "wide"),
    ),
    CommandSpec(
        name="helm-list",
        description="Installed Helm releases",
        command=("helm", "list", "-A"),
    ),
    CommandSpec(
        name="systemd-analyze",
        description="systemd-analyze blame to highlight slow units",
        command=("systemd-analyze", "blame"),
    ),
    CommandSpec(
        name="compose-ps",
        description="Docker compose service status",
        command=("docker", "compose", "-f", "/opt/projects/docker-compose.yml", "ps"),
    ),
    CommandSpec(
        name="compose-logs",
        description="Recent docker compose logs for bundled projects",
        command=(
            "docker",
            "compose",
            "-f",
            "/opt/projects/docker-compose.yml",
            "logs",
            "--tail",
            "400",
        ),
    ),
    CommandSpec(
        name="journal-projects-compose",
        description="projects-compose.service journal excerpt",
        command=(
            "journalctl",
            "-u",
            "projects-compose.service",
            "--no-pager",
            "--since",
            "-6h",
        ),
    ),
    CommandSpec(
        name="journal-k3s",
        description="k3s service journal excerpt",
        command=("journalctl", "-u", "k3s.service", "--no-pager", "--since", "-6h"),
    ),
    CommandSpec(
        name="pi-node-verifier",
        description="Latest pi_node_verifier run output",
        command=(
            "bash",
            "-lc",
            "if [ -x /opt/sugarkube/pi_node_verifier.sh ]; then "
            "sudo /opt/sugarkube/pi_node_verifier.sh --json --quiet || true; "
            "elif [ -x /usr/local/sbin/pi_node_verifier.sh ]; then "
            "sudo /usr/local/sbin/pi_node_verifier.sh --json --quiet || true; "
            "else echo 'pi_node_verifier.sh not installed'; fi",
        ),
        sudo=False,
    ),
]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect kubectl, helm, docker compose, and journal outputs into a support "
            "bundle tarball."
        )
    )
    parser.add_argument(
        "--host",
        help="Remote host to SSH into. When omitted, run commands locally.",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_REMOTE_USER,
        help=f"SSH user. Defaults to {DEFAULT_REMOTE_USER}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_REMOTE_PORT,
        help=f"SSH port. Defaults to {DEFAULT_REMOTE_PORT}.",
    )
    parser.add_argument(
        "--identity",
        help="Path to SSH identity file passed to ssh -i.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Destination tar.gz path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--first-boot-report",
        default=DEFAULT_FIRST_BOOT_REPORT,
        help=(
            "Path to the first boot report directory to archive. "
            f"Defaults to {DEFAULT_FIRST_BOOT_REPORT}."
        ),
    )
    parser.add_argument(
        "--include-first-boot-report",
        action="store_true",
        help="Archive the first boot report directory when present.",
    )
    parser.add_argument(
        "--extra-command",
        action="append",
        default=[],
        metavar="NAME=COMMAND",
        help=(
            "Additional commands to run. Provide NAME=COMMAND where COMMAND is a shell "
            "snippet executed via bash -lc. Repeat for multiple commands."
        ),
    )
    parser.add_argument(
        "--no-sudo",
        action="store_true",
        help="Do not prefix default commands with sudo when running locally.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Command timeout in seconds for each collected snippet.",
    )
    return parser.parse_args(argv)


@dataclass
class CommandResult:
    name: str
    description: str
    command: Sequence[str]
    returncode: int | None
    stdout_path: str
    stderr_path: str
    error: str | None = None


def build_ssh_prefix(args: argparse.Namespace) -> List[str]:
    if not args.host:
        return []
    prefix = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-p",
        str(args.port),
    ]
    if args.identity:
        prefix.extend(["-i", args.identity])
    prefix.append(f"{args.user}@{args.host}")
    return prefix


def run_command(
    spec: CommandSpec,
    args: argparse.Namespace,
    workdir: Path,
    ssh_prefix: Sequence[str],
) -> CommandResult:
    stdout_path = workdir / f"{spec.name}.stdout.txt"
    stderr_path = workdir / f"{spec.name}.stderr.txt"

    command: Sequence[str]
    if args.host:
        remote_command = list(spec.command)
        if spec.sudo and not args.no_sudo:
            remote_command = ["sudo", "-n", *remote_command]
        quoted = " ".join(shlex.quote(part) for part in remote_command)
        ssh_command = [*ssh_prefix, f"set -o pipefail; {quoted}"]
        exec_command = ssh_command
    else:
        command = list(spec.command)
        if spec.sudo and not args.no_sudo:
            command = ["sudo", "-n", *command]
        exec_command = command

    try:
        completed = subprocess.run(
            exec_command,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        stdout_path.write_text("")
        stderr_path.write_text(str(exc))
        return CommandResult(
            name=spec.name,
            description=spec.description,
            command=list(exec_command),
            returncode=None,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=f"executable not found: {exc}",
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "")
        stderr_path.write_text((exc.stderr or "") + "\ncommand timed out")
        return CommandResult(
            name=spec.name,
            description=spec.description,
            command=list(exec_command),
            returncode=None,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error="timeout",
        )

    stdout_path.write_text(completed.stdout)
    stderr_path.write_text(completed.stderr)

    error: str | None = None
    if completed.returncode != 0:
        if spec.optional:
            error = f"non-zero exit code: {completed.returncode}"
        else:
            error = f"command failed with exit code {completed.returncode}"

    return CommandResult(
        name=spec.name,
        description=spec.description,
        command=list(exec_command),
        returncode=completed.returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        error=error,
    )


def parse_extra_commands(definitions: Iterable[str]) -> List[CommandSpec]:
    specs: List[CommandSpec] = []
    for entry in definitions:
        if "=" not in entry:
            raise SupportBundleError(
                f"Invalid --extra-command '{entry}'. Expected NAME=COMMAND format."
            )
        name, command = entry.split("=", 1)
        name = name.strip()
        command = command.strip()
        if not name or not command:
            raise SupportBundleError(
                f"Invalid --extra-command '{entry}'. Name and command must be non-empty."
            )
        specs.append(
            CommandSpec(
                name=name,
                description=f"Custom command: {command}",
                command=("bash", "-lc", command),
                sudo=False,
                optional=True,
            )
        )
    return specs


def archive_first_boot_report(
    args: argparse.Namespace,
    workdir: Path,
    ssh_prefix: Sequence[str],
) -> str | None:
    if not args.include_first_boot_report:
        return None
    archive_path = workdir / "first-boot-report.tar.gz"
    if args.host:
        remote = shlex.quote(args.first_boot_report)
        remote_cmd = 'sudo tar -C $(dirname "' + remote + '") -czf - $(basename "' + remote + '")'
        ssh_command = [*ssh_prefix, remote_cmd]
        try:
            with archive_path.open("wb") as fh:
                completed = subprocess.run(
                    ssh_command,
                    check=False,
                    stdout=fh,
                    stderr=subprocess.PIPE,
                )
        except FileNotFoundError as exc:
            archive_path.write_text(str(exc))
            return str(archive_path)
        if completed.returncode != 0:
            archive_path.write_bytes(completed.stderr)
            return str(archive_path)
    else:
        target = Path(args.first_boot_report)
        if not target.exists():
            archive_path.write_text(
                f"first boot report directory '{target}' not found on local host"
            )
            return str(archive_path)
        with tarfile.open(archive_path, "w:gz") as bundle:
            bundle.add(target, arcname=target.name)
    return str(archive_path)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    ssh_prefix = build_ssh_prefix(args)

    command_specs = list(DEFAULT_COMMANDS)
    command_specs.extend(parse_extra_commands(args.extra_command))

    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix="sugarkube-support-") as tmp:
        workdir = Path(tmp)
        metadata: dict[str, object] = {
            "generated_at": timestamp,
            "host": args.host or "local",
            "commands": [],
        }

        for spec in command_specs:
            result = run_command(spec, args, workdir, ssh_prefix)
            metadata["commands"].append(asdict(result))

        fb_archive = archive_first_boot_report(args, workdir, ssh_prefix)
        if fb_archive:
            metadata["first_boot_report"] = fb_archive

        metadata_path = workdir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True))

        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output_path, "w:gz") as bundle:
            for item in workdir.iterdir():
                bundle.add(item, arcname=item.name)

    print(f"Support bundle written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
