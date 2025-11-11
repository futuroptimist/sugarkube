"""Regression tests for the BATS ncat stub."""

import socket
import subprocess
import sys
import time
from pathlib import Path

STUB_PATH = Path(__file__).parent / "bats" / "fixtures" / "ncat_stub.py"


def test_stub_exists() -> None:
    assert STUB_PATH.is_file(), "ncat stub fixture missing"


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"stub did not begin listening on port {port}")


def test_stub_accepts_connections_with_combined_flags() -> None:
    port = _allocate_port()
    proc = subprocess.Popen(
        [str(STUB_PATH), "-lk", "127.0.0.1", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_stub_accepts_connections_with_separate_flags() -> None:
    port = _allocate_port()
    proc = subprocess.Popen(
        [sys.executable, str(STUB_PATH), "-l", "-k", "127.0.0.1", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    finally:
        proc.terminate()
        proc.wait(timeout=5)
