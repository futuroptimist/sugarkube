#!/usr/bin/env python3
"""Minimal ncat replacement for BATS tests."""
from __future__ import annotations

import signal
import socket
import sys
from contextlib import closing


def _parse_args(argv: list[str]) -> tuple[str, int, bool]:
    host = "0.0.0.0"
    port: int | None = None
    keep_open = False

    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg.startswith("-"):
            # Support combined flags like -lk as well as separate -l -k.
            if "k" in arg:
                keep_open = True
            # `-l` is implied for the stub; nothing else to do.
            idx += 1
            continue
        host = arg
        idx += 1
        if idx >= len(argv):
            raise ValueError("port argument missing")
        try:
            port = int(argv[idx])
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"invalid port: {argv[idx]}") from exc
        idx += 1

    if port is None:
        raise ValueError("port argument missing")
    return host, port, keep_open


def _install_signal_handlers(sock: socket.socket) -> None:
    def _shutdown_handler(*_args: object) -> None:
        # Closing the listening socket unblocks accept() and exits cleanly.
        try:
            sock.close()
        finally:
            sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _shutdown_handler)


def main(argv: list[str]) -> int:
    try:
        host, port, keep_open = _parse_args(argv)
    except ValueError as err:
        print(f"ncat_stub: {err}", file=sys.stderr)
        return 2

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen()
        _install_signal_handlers(sock)

        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                # Socket closed by signal handler; exit gracefully.
                return 0
            conn.close()
            if not keep_open:
                return 0


def _run() -> int:
    return main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(_run())
