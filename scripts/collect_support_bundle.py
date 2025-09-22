#!/usr/bin/env python3
"""Collect Kubernetes, systemd, and compose diagnostics from a Sugarkube Pi."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

DEFAULT_COMMAND_TIMEOUT = 120
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_OUTPUT_DIR = "support-bundles"
DEFAULT_USER = "pi"
KUBECONFIG_PATH = "/etc/rancher/k3s/k3s.yaml"
COMPOSE_FILE = "/opt/projects/docker-compose.yml"
COMPOSE_PROJECT_DIR = "/opt/projects"


@dataclass(frozen=True)
class CommandSpec:
    """Description of a remote command to capture."""

    output_path: Path
    remote_command: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "output_path": self.output_path.as_posix(),
            "remote_command": self.remote_command,
            "description": self.description,
        }


def default_specs() -> List[CommandSpec]:
    """Return the default commands captured in every bundle."""

    kube_env = "sudo env KUBECONFIG=" + shlex.quote(KUBECONFIG_PATH) + " "
    docker_base = (
        "sudo docker compose --project-directory "
        + shlex.quote(COMPOSE_PROJECT_DIR)
        + " -f "
        + shlex.quote(COMPOSE_FILE)
    )

    return [
        CommandSpec(
            Path("kubernetes/events.txt"),
            f"{kube_env} kubectl get events --all-namespaces --sort-by=.lastTimestamp -o wide",
            "Chronological Kubernetes events to pinpoint regressions.",
        ),
        CommandSpec(
            Path("kubernetes/pods.txt"),
            f"{kube_env} kubectl get pods --all-namespaces -o wide",
            "Running workloads across namespaces.",
        ),
        CommandSpec(
            Path("kubernetes/nodes.txt"),
            f"{kube_env} kubectl describe nodes",
            "Node inventory with taints, addresses, and resource pressure.",
        ),
        CommandSpec(
            Path("helm/releases.txt"),
            f"{kube_env} helm list -A",
            "Helm release summary for the cluster.",
        ),
        CommandSpec(
            Path("systemd/systemd-analyze-blame.txt"),
            "sudo systemd-analyze blame",
            "Boot timing to surface slow units.",
        ),
        CommandSpec(
            Path("systemd/systemd-critical-chain.txt"),
            "sudo systemd-analyze critical-chain",
            "Critical boot path for stalled services.",
        ),
        CommandSpec(
            Path("systemd/failed-units.txt"),
            "sudo systemctl list-units --failed",
            "Failed systemd units after boot.",
        ),
        CommandSpec(
            Path("compose/projects-compose.log"),
            ("sudo journalctl --no-pager --output=short-precise " "-u projects-compose.service"),
            "projects-compose service journal.",
        ),
        CommandSpec(
            Path("compose/projects-compose-status.txt"),
            "sudo systemctl status projects-compose.service",
            "Systemd status for the compose stack.",
        ),
        CommandSpec(
            Path("compose/docker-compose-logs.txt"),
            f"{docker_base} logs --tail=400 --timestamps",
            "Docker Compose logs for token.place, dspace, and observability exporters.",
        ),
        CommandSpec(
            Path("compose/docker-compose-ps.txt"),
            f"{docker_base} ps",
            "Current container status reported by docker compose.",
        ),
        CommandSpec(
            Path("journals/journalctl-boot.txt"),
            "sudo journalctl -b --no-pager --output=short-precise",
            "Complete journal for the current boot.",
        ),
        CommandSpec(
            Path("journals/self-heal.log"),
            "sudo journalctl --no-pager --output=short-precise -u 'sugarkube-self-heal@*'",
            "Self-heal escalation attempts and captured failures.",
        ),
        CommandSpec(
            Path("journals/first-boot.log"),
            "sudo journalctl --no-pager --output=short-precise -u first-boot.service",
            "first-boot.service retries and verifier output.",
        ),
        CommandSpec(
            Path("journals/k3s.log"),
            "sudo journalctl --no-pager --output=short-precise -u k3s.service",
            "k3s control-plane journal entries.",
        ),
        CommandSpec(
            Path("storage/df.txt"),
            "df -h",
            "Filesystem usage snapshot.",
        ),
        CommandSpec(
            Path("storage/mounts.txt"),
            "mount",
            "Mounted filesystems and options.",
        ),
        CommandSpec(
            Path("reports/first-boot-report-tree.txt"),
            "ls -R /boot/first-boot-report",
            "List of generated first-boot reports for quick inspection.",
        ),
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("SSH into a Sugarkube Pi and collect diagnostics into a support bundle.")
    )
    parser.add_argument("host", help="Hostname or IP address of the Pi to inspect.")
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help=f"SSH username. Defaults to '{DEFAULT_USER}'.",
    )
    parser.add_argument(
        "--identity",
        help="Path to an SSH private key passed to ssh -i.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="SSH port. Defaults to 22.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where support bundles are stored. Defaults to support-bundles.",
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout for each remote command (seconds). " f"Defaults to {DEFAULT_COMMAND_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=DEFAULT_CONNECT_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout for establishing the SSH connection (seconds). "
            f"Defaults to {DEFAULT_CONNECT_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Extra -o options passed directly to ssh (repeatable).",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip creating a compressed tarball (leave raw files on disk).",
    )
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        metavar="PATH:COMMAND:DESCRIPTION",
        help=("Extra command to capture (repeatable). Format: output/path.txt:command:description"),
    )
    return parser.parse_args(argv)


def parse_extra_specs(entries: Iterable[str]) -> List[CommandSpec]:
    specs: List[CommandSpec] = []
    for entry in entries:
        parts = entry.split(":", 2)
        if len(parts) != 3:
            raise ValueError("Invalid --spec entry. Expected output_path:command:description")
        output_str, command, description = parts
        output_path = Path(output_str)
        if output_path.is_absolute():
            raise ValueError("Support bundle paths must be relative")
        specs.append(CommandSpec(output_path, command, description))
    return specs


def build_bundle_dir(base: Path, host: str, timestamp: datetime) -> Path:
    safe_host = host.replace("/", "_").replace(":", "_")
    name = f"{safe_host}-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    bundle_dir = base / name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    return bundle_dir


def build_ssh_command(args: argparse.Namespace, remote_command: str) -> List[str]:
    destination = f"{args.user}@{args.host}" if args.user else args.host
    cmd: List[str] = [
        "ssh",
        "-o",
        f"ConnectTimeout={args.connect_timeout}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
    ]
    if args.identity:
        cmd.extend(["-i", args.identity])
    if args.port and args.port != 22:
        cmd.extend(["-p", str(args.port)])
    for option in args.ssh_option:
        cmd.extend(["-o", option])
    cmd.append(destination)
    cmd.extend(["bash", "-lc", f"set -o pipefail; {remote_command}"])
    return cmd


def write_command_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def execute_specs(
    args: argparse.Namespace,
    specs: Sequence[CommandSpec],
    bundle_dir: Path,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for spec in specs:
        output_path = bundle_dir / spec.output_path
        ssh_cmd = build_ssh_command(args, spec.remote_command)
        try:
            completed = subprocess.run(
                ssh_cmd,
                check=False,
                text=True,
                capture_output=True,
                timeout=args.command_timeout,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            status = "success" if completed.returncode == 0 else "failed"
            payload_lines = [
                f"# {spec.description}\n",
                f"# Command: {spec.remote_command}\n",
                f"# Exit status: {completed.returncode}\n",
                "\n",
                stdout or "(no output)\n",
            ]
            if stderr:
                payload_lines.extend(
                    [
                        "\n# stderr\n\n",
                        stderr,
                    ]
                )
            write_command_output(output_path, "".join(payload_lines))
            results.append(
                {
                    "command": spec.to_dict(),
                    "exit_code": completed.returncode,
                    "status": status,
                }
            )
        except subprocess.TimeoutExpired:
            write_command_output(
                output_path,
                (
                    f"# {spec.description}\n# Command: {spec.remote_command}\n"
                    f"# Timed out after {args.command_timeout} seconds\n"
                ),
            )
            results.append(
                {
                    "command": spec.to_dict(),
                    "exit_code": None,
                    "status": "timeout",
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            write_command_output(
                output_path,
                (f"# {spec.description}\n# Command: {spec.remote_command}\n" f"# Error: {exc}\n"),
            )
            results.append(
                {
                    "command": spec.to_dict(),
                    "exit_code": None,
                    "status": "error",
                    "error": str(exc),
                }
            )
    return results


def archive_bundle(bundle_dir: Path) -> Path:
    tar_path = bundle_dir.with_suffix(".tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=bundle_dir.name)
    return tar_path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        extra_specs = parse_extra_specs(args.spec)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    specs = default_specs() + extra_specs

    output_root = Path(args.output_dir)
    timestamp = datetime.now(timezone.utc)
    bundle_dir = build_bundle_dir(output_root, args.host, timestamp)

    results = execute_specs(args, specs, bundle_dir)

    summary = {
        "host": args.host,
        "user": args.user,
        "timestamp": timestamp.isoformat(),
        "bundle": bundle_dir.name,
        "results": results,
    }
    write_command_output(bundle_dir / "summary.json", json.dumps(summary, indent=2))

    any_success = any(item["status"] == "success" for item in results)
    if not args.no_archive:
        tar_path = archive_bundle(bundle_dir)
    else:
        tar_path = None

    if tar_path:
        print(f"Support bundle saved to {tar_path}")
    else:
        print(f"Support bundle saved to {bundle_dir}")

    if not any_success:
        print("warning: no commands succeeded", file=sys.stderr)
        return 1

    failed = [item for item in results if item["status"] != "success"]
    if failed:
        print(
            f"warning: {len(failed)} command(s) failed; see summary.json for details",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
