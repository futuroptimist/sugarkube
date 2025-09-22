#!/usr/bin/env python3
"""Helpers for rehearsing k3s multi-node joins without touching production clusters."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

DEFAULT_SSH_PORT = 22
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_API_PORT = 6443
DEFAULT_API_TIMEOUT = 5
DEFAULT_USER = "pi"
DEFAULT_SECRET_PATH = "/boot/sugarkube-node-token"


class RehearsalError(RuntimeError):
    """Raised when the rehearsal flow cannot complete."""


@dataclass
class ServerStatus:
    host: str
    join_secret: str
    api_url: str
    nodes: List[Dict[str, object]]


@dataclass
class AgentStatus:
    host: str
    payload: Dict[str, object]
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.payload.get("api_reachable"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check control-plane readiness, confirm agent prerequisites over SSH, "
            "and emit a join command template so you can practice scaling before "
            "touching production nodes."
        )
    )
    parser.add_argument("server", help="SSH host for the control-plane node.")
    parser.add_argument(
        "--server-user",
        default=DEFAULT_USER,
        help=f"SSH user for the control-plane. Defaults to '{DEFAULT_USER}'.",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=DEFAULT_SSH_PORT,
        help=f"SSH port for the control-plane. Defaults to {DEFAULT_SSH_PORT}.",
    )
    parser.add_argument(
        "--server-ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Additional -o options passed to the control-plane ssh command (repeatable).",
    )
    parser.add_argument(
        "--server-no-sudo",
        action="store_true",
        help="Run control-plane commands without sudo. Requires direct root access.",
    )
    parser.add_argument(
        "--secret-path",
        default=DEFAULT_SECRET_PATH,
        help=(
            "Path to the mirrored join secret on the control-plane. Defaults to "
            f"{DEFAULT_SECRET_PATH}."
        ),
    )
    parser.add_argument(
        "--server-url",
        help=(
            "Override the k3s API URL. Defaults to https://<control-plane-address>:6443 using "
            "the node InternalIP when available."
        ),
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=DEFAULT_API_PORT,
        help=f"k3s API port exposed by the control-plane. Defaults to {DEFAULT_API_PORT}.",
    )
    parser.add_argument(
        "--api-timeout",
        type=int,
        default=DEFAULT_API_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Timeout (seconds) for agent connectivity probes to the k3s API. "
            f"Defaults to {DEFAULT_API_TIMEOUT}."
        ),
    )
    parser.add_argument(
        "--agents",
        nargs="*",
        metavar="HOST",
        help="Zero or more SSH hosts representing prospective worker nodes to preflight.",
    )
    parser.add_argument(
        "--agent-user",
        default=DEFAULT_USER,
        help=f"SSH user for worker nodes. Defaults to '{DEFAULT_USER}'.",
    )
    parser.add_argument(
        "--agent-port",
        type=int,
        default=DEFAULT_SSH_PORT,
        help=f"SSH port for worker nodes. Defaults to {DEFAULT_SSH_PORT}.",
    )
    parser.add_argument(
        "--agent-ssh-option",
        action="append",
        default=[],
        metavar="OPTION",
        help="Additional -o options passed to agent ssh commands (repeatable).",
    )
    parser.add_argument(
        "--agent-no-sudo",
        action="store_true",
        help="Run agent preflight checks without sudo (skips privileged filesystem probes).",
    )
    parser.add_argument(
        "--identity",
        help="Path to an SSH identity used for both control-plane and worker connections.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=DEFAULT_CONNECT_TIMEOUT,
        metavar="SECONDS",
        help=("Connection timeout (seconds) for SSH. " f"Defaults to {DEFAULT_CONNECT_TIMEOUT}."),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON in addition to human-friendly summaries.",
    )
    parser.add_argument(
        "--reveal-secret",
        action="store_true",
        help="Print the full join secret instead of redacting it (handle with care).",
    )
    parser.add_argument(
        "--save-secret",
        help="Write the retrieved join secret to this local file with 0600 permissions.",
    )
    return parser.parse_args(argv)


def build_ssh_command(
    host: str,
    *,
    user: str,
    port: int,
    identity: Optional[str],
    options: Iterable[str],
    connect_timeout: int,
    remote_command: str,
) -> List[str]:
    destination = f"{user}@{host}" if user else host
    command = [
        "ssh",
        "-p",
        str(port),
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
    ]
    for opt in options:
        command.extend(["-o", opt])
    if identity:
        command.extend(["-i", identity])
    command.append(destination)
    command.append(remote_command)
    return command


def run_ssh(command: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True)


def fetch_join_secret(args: argparse.Namespace) -> str:
    sudo_prefix = "" if args.server_no_sudo else "sudo -n "
    remote_command = f"{sudo_prefix}cat {shlex.quote(args.secret_path)}"
    command = build_ssh_command(
        args.server,
        user=args.server_user,
        port=args.server_port,
        identity=args.identity,
        options=args.server_ssh_option,
        connect_timeout=args.connect_timeout,
        remote_command=remote_command,
    )
    result = run_ssh(command)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RehearsalError(
            "Failed to read the control-plane join secret. "
            "Ensure sudo can run non-interactively or pass --server-no-sudo. "
            f"stderr: {stderr or 'no stderr captured'}"
        )
    secret_value = result.stdout.strip()
    if not secret_value:
        raise RehearsalError("Control-plane join secret file was empty.")
    return secret_value


def fetch_node_inventory(args: argparse.Namespace) -> List[Dict[str, object]]:
    sudo_prefix = "" if args.server_no_sudo else "sudo -n "
    remote_command = f"{sudo_prefix}k3s kubectl get nodes -o json"
    command = build_ssh_command(
        args.server,
        user=args.server_user,
        port=args.server_port,
        identity=args.identity,
        options=args.server_ssh_option,
        connect_timeout=args.connect_timeout,
        remote_command=remote_command,
    )
    result = run_ssh(command)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RehearsalError(
            "Failed to query node inventory via k3s kubectl. "
            "Confirm k3s is installed and the SSH user has sudo. "
            f"stderr: {stderr or 'no stderr captured'}"
        )
    payload = result.stdout.strip()
    if not payload:
        raise RehearsalError("k3s kubectl returned no output when listing nodes.")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RehearsalError("Unable to parse kubectl JSON output.") from exc
    items = data.get("items")
    if not isinstance(items, list):
        raise RehearsalError("kubectl JSON payload missing 'items' list.")
    return items


def node_is_control_plane(node: Dict[str, object]) -> bool:
    metadata = node.get("metadata") if isinstance(node, dict) else {}
    labels = metadata.get("labels") if isinstance(metadata, dict) else {}
    if not isinstance(labels, dict):
        return False
    keys = {
        "node-role.kubernetes.io/control-plane",
        "node-role.kubernetes.io/master",
        "node-role.kubernetes.io/server",
    }
    return any(key in labels for key in keys)


def extract_internal_ip(node: Dict[str, object]) -> Optional[str]:
    status = node.get("status") if isinstance(node, dict) else {}
    addresses = status.get("addresses") if isinstance(status, dict) else []
    if not isinstance(addresses, list):
        return None
    for entry in addresses:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "InternalIP" and entry.get("address"):
            return str(entry["address"])
    return None


def pick_control_plane_address(
    nodes: Iterable[Dict[str, object]],
    fallback: str,
) -> str:
    control_plane_nodes = [node for node in nodes if node_is_control_plane(node)]
    for candidate in control_plane_nodes:
        ip = extract_internal_ip(candidate)
        if ip:
            return ip
    for candidate in nodes:
        ip = extract_internal_ip(candidate)
        if ip:
            return ip
    return fallback


def summarise_node_conditions(nodes: Iterable[Dict[str, object]]) -> List[str]:
    summaries: List[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        metadata = node.get("metadata") if isinstance(node, dict) else {}
        name = metadata.get("name") if isinstance(metadata, dict) else "<unknown>"
        status = node.get("status") if isinstance(node, dict) else {}
        conditions = status.get("conditions") if isinstance(status, dict) else []
        ready = "Unknown"
        if isinstance(conditions, list):
            for cond in conditions:
                if not isinstance(cond, dict):
                    continue
                if cond.get("type") == "Ready":
                    ready = str(cond.get("status", "Unknown"))
                    break
        role = "control-plane" if node_is_control_plane(node) else "worker"
        summaries.append(f"{name}: Ready={ready} ({role})")
    return summaries


def determine_api_url(args: argparse.Namespace, nodes: List[Dict[str, object]]) -> str:
    if args.server_url:
        return args.server_url
    host = pick_control_plane_address(nodes, args.server)
    return f"https://{host}:{args.api_port}"


def parse_api_host(api_url: str) -> str:
    parsed = urlparse(api_url)
    if not parsed.hostname:
        raise RehearsalError(f"Unable to determine host from API URL: {api_url}")
    return parsed.hostname


def collect_server_status(args: argparse.Namespace) -> ServerStatus:
    join_secret = fetch_join_secret(args)
    nodes = fetch_node_inventory(args)
    api_url = determine_api_url(args, nodes)
    return ServerStatus(host=args.server, join_secret=join_secret, api_url=api_url, nodes=nodes)


def build_agent_python(api_host: str, api_port: int, timeout: int) -> str:
    return textwrap.dedent(
        f"""
        import json
        import os
        import shutil
        import socket
        import subprocess
        import sys

        result = {{}}
        result["hostname"] = os.uname().nodename

        try:
            sock = socket.create_connection(("{api_host}", {api_port}), timeout={timeout})
        except OSError as exc:
            result["api_reachable"] = False
            result["api_error"] = str(exc)
        else:
            sock.close()
            result["api_reachable"] = True
            result["api_error"] = ""

        curl_bin = shutil.which("curl")
        if curl_bin:
            curl = subprocess.run(
                [curl_bin, "-sfI", "https://get.k3s.io"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            result["install_script_reachable"] = curl.returncode == 0
            if curl.returncode != 0:
                result["install_script_error"] = f"curl exited {{curl.returncode}}"
            else:
                result["install_script_error"] = ""
        else:
            result["install_script_reachable"] = False
            result["install_script_error"] = "curl binary not found"

        systemctl = shutil.which("systemctl")
        if systemctl:
            svc = subprocess.run(
                [systemctl, "is-active", "k3s-agent"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            result["k3s_agent_active"] = svc.returncode == 0
            output = (svc.stdout or svc.stderr).strip()
            result["k3s_agent_state"] = output or ("exit code " + str(svc.returncode))
        else:
            result["k3s_agent_active"] = False
            result["k3s_agent_state"] = "systemctl not available"

        result["registration_present"] = os.path.exists("/etc/rancher/k3s/registration.yaml")
        result["data_dir_exists"] = os.path.isdir("/var/lib/rancher/k3s/agent")

        print(json.dumps(result))
        """
    )


def collect_agent_status(host: str, args: argparse.Namespace, api_host: str) -> AgentStatus:
    sudo_prefix = "" if args.agent_no_sudo else "sudo -n "
    python_body = build_agent_python(api_host, args.api_port, args.api_timeout)
    remote_command = f"{sudo_prefix}python3 - <<'PY'\n{python_body}\nPY"
    command = build_ssh_command(
        host,
        user=args.agent_user,
        port=args.agent_port,
        identity=args.identity,
        options=args.agent_ssh_option,
        connect_timeout=args.connect_timeout,
        remote_command=remote_command,
    )
    result = run_ssh(command)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return AgentStatus(
            host=host,
            payload={},
            error=(
                f"SSH preflight failed with exit code {result.returncode}: "
                f"{stderr or 'no stderr captured'}"
            ),
        )
    output = result.stdout.strip()
    if not output:
        return AgentStatus(host=host, payload={}, error="Agent preflight produced no output")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return AgentStatus(host=host, payload={}, error=f"Failed to parse agent JSON: {exc}")
    if not isinstance(payload, dict):
        return AgentStatus(host=host, payload={}, error="Agent JSON payload was not a dict")
    return AgentStatus(host=host, payload=payload)


def redact_join_secret(join_secret: str) -> str:
    if len(join_secret) <= 8:
        return "***"
    return f"{join_secret[:4]}…{join_secret[-4:]}"


def format_agent_summary(agent: AgentStatus) -> str:
    if agent.error:
        return f"[{agent.host}] ERROR: {agent.error}"
    status = "PASS" if agent.success else "WARN"
    payload = agent.payload
    api_state = "ok" if payload.get("api_reachable") else "unreachable"
    install_state = "ok" if payload.get("install_script_reachable") else "unreachable"
    agent_state = payload.get("k3s_agent_state", "unknown")
    reg_hint = "present" if payload.get("registration_present") else "missing"
    data_dir = "present" if payload.get("data_dir_exists") else "missing"
    return (
        f"[{agent.host}] {status}: api={api_state}, get.k3s.io={install_state}, "
        f"k3s-agent={agent_state}, registration={reg_hint}, data-dir={data_dir}"
    )


def write_join_secret(path: str, join_secret: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(join_secret + "\n")
    subprocess.run(["chmod", "600", path], check=False)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        server = collect_server_status(args)
    except RehearsalError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    api_host = parse_api_host(server.api_url)
    node_summaries = summarise_node_conditions(server.nodes)
    print("Control-plane node status:")
    for line in node_summaries:
        print(f"  - {line}")

    token_for_display = (
        server.join_secret if args.reveal_secret else redact_join_secret(server.join_secret)
    )
    print("")
    print("Join command rehearsal (replace <node-name> per host):")
    token_env = "K3S_" + "TOKEN"
    print(f"  export K3S_URL={server.api_url}")
    print(f"  export {token_env}={token_for_display}")
    print(
        "  curl -sfL https://get.k3s.io | "
        'sudo INSTALL_K3S_EXEC="agent --with-node-id --node-name <node-name>" sh -'
    )
    if not args.reveal_secret:
        print(
            "  # Run again with --reveal-secret or use --save-secret to capture the secret locally."
        )

    if args.save_secret:
        write_join_secret(args.save_secret, server.join_secret)
        print(f"\nSaved join secret to {args.save_secret} (chmod 600).")

    agent_reports: List[AgentStatus] = []
    if args.agents:
        print("\nAgent preflight:")
        for host in args.agents:
            report = collect_agent_status(host, args, api_host)
            agent_reports.append(report)
            print(format_agent_summary(report))

    if args.json:
        payload = {
            "server": {
                "host": server.host,
                "api_url": server.api_url,
                "join_secret": server.join_secret if args.reveal_secret else None,
                "nodes": node_summaries,
            },
            "agents": [
                {
                    "host": report.host,
                    "success": report.success,
                    "error": report.error,
                    "payload": report.payload,
                }
                for report in agent_reports
            ],
        }
        print(json.dumps(payload, indent=2))

    warnings = [report for report in agent_reports if not report.success]
    return 0 if not warnings else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
