"""Connectivity probes for network namespace fixtures."""

from __future__ import annotations

import subprocess
import textwrap
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_TCP_PROBE_PORT = 53535
DEFAULT_SERVER_START_DELAY = 0.2
DEFAULT_RETRY_DELAY = 0.25


@dataclass
class NamespaceProbeResult:
    """Structured result describing namespace connectivity probes."""

    ok: bool
    attempts: int
    reason: str | None = None
    errors: list[str] | None = None

    def __bool__(self) -> bool:  # pragma: no cover - exercised indirectly via callers
        return self.ok


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
    retry_delay: float = DEFAULT_RETRY_DELAY,
    attempts: int = 2,
    run_cmd: ProbeRunner = subprocess.run,
    popen_cmd: ProbeSpawner = subprocess.Popen,
    sleep_fn: SleepFn = time.sleep,
) -> NamespaceProbeResult:
    """Attempt a TCP handshake between namespaces without relying on ICMP ping.

    The probe starts a short-lived TCP listener inside ``server_namespace`` and attempts a
    connection from ``client_namespace``.  The listener exits once the handshake completes so
    the fixture can clean up deterministically.  ``ok`` is set to ``True`` when the client
    command succeeds and the server process exits with ``0``.  ``server_start_delay`` configures
    how long to wait before attempting the client connection so the listener can bind and listen
    reliably on slower systems.  Retries provide resilience on hosts with slower namespace setup,
    and diagnostic reasons capture the last failure mode to aid skips in CI.
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

    errors: list[str] = []

    for attempt in range(1, max(attempts, 1) + 1):
        server_proc: subprocess.Popen[str] | None = None
        success = False

        try:
            server_proc = popen_cmd(
                ["ip", "netns", "exec", server_namespace, "python3", "-c", server_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception as exc:
            errors.append(f"spawn attempt {attempt} failed: {exc}")
            if attempt < attempts:
                sleep_fn(retry_delay)
                continue
            return NamespaceProbeResult(
                ok=False,
                attempts=attempt,
                reason=errors[-1],
                errors=errors,
            )

        try:
            sleep_fn(server_start_delay)
            client_result = run_cmd(
                ["ip", "netns", "exec", client_namespace, "python3", "-c", client_script],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if client_result.returncode != 0:
                message = client_result.stderr.strip() or client_result.stdout.strip()
                message = message or f"client exit {client_result.returncode}"
                errors.append(f"client attempt {attempt} failed: {message}")
                continue

            server_exit = server_proc.wait(timeout=3)
            if server_exit == 0:
                success = True
                return NamespaceProbeResult(
                    ok=True,
                    attempts=attempt,
                    errors=errors or None,
                )

            errors.append(f"server attempt {attempt} exited {server_exit}")
        except Exception as exc:  # pragma: no cover - exercised via exception branches in tests
            errors.append(f"probe attempt {attempt} raised: {exc}")
        finally:
            if server_proc is not None and not success:
                try:
                    server_proc.terminate()
                except Exception:
                    # Best-effort cleanup during termination; ignore errors from already-exited
                    # processes.
                    pass
                try:
                    server_proc.wait(timeout=1)
                except Exception:
                    # Ignore errors while waiting for process exit during cleanup.
                    pass

        if attempt < attempts:
            sleep_fn(retry_delay)

    return NamespaceProbeResult(
        ok=False,
        attempts=max(attempts, 1),
        reason=errors[-1] if errors else "namespace probe failed",
        errors=errors or None,
    )
