"""Connectivity probes for network namespace fixtures."""

from __future__ import annotations

import subprocess
import textwrap
import time
from typing import Callable

DEFAULT_TCP_PROBE_PORT = 53535
DEFAULT_SERVER_START_DELAY = 0.2


ProbeRunner = Callable[..., subprocess.CompletedProcess[str]]
ProbeSpawner = Callable[..., subprocess.Popen[str]]
SleepFn = Callable[[float], None]


def probe_namespace_connectivity(
    client_namespace: str,
    server_namespace: str,
    server_ip: str,
    *,
    port: int = DEFAULT_TCP_PROBE_PORT,
    server_start_delay: float = DEFAULT_SERVER_START_DELAY,
    run_cmd: ProbeRunner = subprocess.run,
    popen_cmd: ProbeSpawner = subprocess.Popen,
    sleep_fn: SleepFn = time.sleep,
) -> bool:
    """Attempt a TCP handshake between namespaces without relying on ICMP ping.

    The probe starts a short-lived TCP listener inside ``server_namespace`` and attempts a
    connection from ``client_namespace``.  The listener exits once the handshake completes so
    the fixture can clean up deterministically.  ``True`` is returned when the client command
    succeeds and the server process exits with ``0``.  ``server_start_delay`` configures how long
    to wait before attempting the client connection so the listener can bind and listen reliably
    on slower systems.
    """

    server_script = textwrap.dedent(
        f"""
        import socket
        import sys

        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("{server_ip}", {port}))
            sock.listen(1)
            sock.settimeout(2)
            try:
                conn, _ = sock.accept()
                conn.close()
                sys.exit(0)
            except Exception:
                sys.exit(1)
        """
    ).strip()

    client_script = textwrap.dedent(
        f"""
        import socket
        import sys

        try:
            with socket.socket() as sock:
                sock.settimeout(2)
                sock.connect(("{server_ip}", {port}))
        except Exception:
            sys.exit(1)
        sys.exit(0)
        """
    ).strip()

    server_proc: subprocess.Popen[str] | None = None
    try:
        server_proc = popen_cmd(
            ["ip", "netns", "exec", server_namespace, "python3", "-c", server_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return False

    try:
        sleep_fn(server_start_delay)
        client_result = run_cmd(
            ["ip", "netns", "exec", client_namespace, "python3", "-c", client_script],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if client_result.returncode != 0:
            return False

        server_exit = server_proc.wait(timeout=3)
        return server_exit == 0
    except Exception:
        return False
    finally:
        if server_proc is not None:
            try:
                server_proc.terminate()
            except Exception:
                # Best-effort cleanup during termination; ignore errors from already-exited
                # processes.
                pass
            try:
                server_proc.wait(timeout=1)
            except Exception:
                # Ignore errors while waiting for the process to exit during best-effort cleanup.
                pass
