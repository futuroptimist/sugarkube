"""Namespace connectivity probes used by mDNS integration tests."""

from __future__ import annotations

import subprocess
import textwrap
from typing import Callable, Sequence


def probe_namespace_connectivity(
    ns1: str,
    ns2: str,
    target_ip: str,
    *,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    run_command: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout_secs: float = 5.0,
) -> bool:
    """Verify connectivity between namespaces using a TCP round trip.

    The probe starts a short-lived TCP server inside ``ns2`` and connects to it from
    ``ns1``. If either side fails to start or the connection cannot be established,
    ``False`` is returned so callers can skip expensive integration tests early.
    """

    server_script = textwrap.dedent(
        f"""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("{target_ip}", 18080))
        sock.listen(1)
        conn, _ = sock.accept()
        conn.recv(16)
        conn.sendall(b"ok")
        conn.close()
        sock.close()
        """
    ).strip()

    server_cmd: Sequence[str] = [
        "ip",
        "netns",
        "exec",
        ns2,
        "python",
        "-u",
        "-c",
        server_script,
    ]

    client_script = textwrap.dedent(
        f"""
        import socket
        import sys
        sock = socket.create_connection(("{target_ip}", 18080), timeout={timeout_secs})
        sock.sendall(b"ping")
        sock.settimeout({timeout_secs})
        data = sock.recv(2)
        sock.close()
        sys.exit(0 if data == b"ok" else 1)
        """
    ).strip()

    client_cmd: Sequence[str] = [
        "ip",
        "netns",
        "exec",
        ns1,
        "python",
        "-c",
        client_script,
    ]

    server_proc = popen_factory(
        server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        client_result = run_command(
            client_cmd, capture_output=True, text=True, check=False
        )
        if client_result.returncode != 0:
            return False

        server_proc.wait(timeout=timeout_secs)
        return True
    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=1)
            except Exception:
                server_proc.kill()
