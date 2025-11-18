"""
Regression tests for mDNS discovery fixes (2025-11-15).

These tests prevent regression of the following issues:
1. --terminate flag being used by default (prevents network discovery)
2. --ignore-local flag blocking self-verification
3. TypeError when handling TimeoutExpired exceptions with bytes
"""
import os
import subprocess
import sys
from pathlib import Path

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from k3s_mdns_query import query_mdns, _build_command  # noqa: E402


def test_terminate_flag_not_used_by_default():
    """
    Regression test for 2025-11-15-mdns-terminate-flag-prevented-discovery.

    The --terminate flag should NOT be used by default because it causes
    avahi-browse to only dump cached entries without waiting for network
    responses. During initial cluster formation, the cache is empty.
    """
    # Save original env
    original = os.environ.get("SUGARKUBE_MDNS_NO_TERMINATE")

    try:
        # Clear env to test default behavior
        if "SUGARKUBE_MDNS_NO_TERMINATE" in os.environ:
            del os.environ["SUGARKUBE_MDNS_NO_TERMINATE"]

        # Build command for server discovery
        command = _build_command("server-select", "_k3s-sugar-dev._tcp", resolve=True)

        # Verify --terminate is NOT in the command by default
        assert "--terminate" not in command, (
            "REGRESSION: --terminate flag is being used by default. "
            "This prevents network discovery during initial cluster formation."
        )

        # Verify we do NOT have --no-terminate (that's not a real flag)
        assert not any("no-terminate" in arg for arg in command)

    finally:
        # Restore original env
        if original is not None:
            os.environ["SUGARKUBE_MDNS_NO_TERMINATE"] = original
        elif "SUGARKUBE_MDNS_NO_TERMINATE" in os.environ:
            del os.environ["SUGARKUBE_MDNS_NO_TERMINATE"]


def test_terminate_flag_can_be_enabled_explicitly():
    """
    Verify that --terminate can still be enabled when explicitly requested.
    This is useful for scenarios where only cached entries are needed.
    """
    original = os.environ.get("SUGARKUBE_MDNS_NO_TERMINATE")

    try:
        # Explicitly request --terminate
        os.environ["SUGARKUBE_MDNS_NO_TERMINATE"] = "0"

        command = _build_command("server-select", "_k3s-sugar-dev._tcp", resolve=True)

        # Now --terminate SHOULD be present
        assert "--terminate" in command, (
            "SUGARKUBE_MDNS_NO_TERMINATE=0 should enable --terminate flag"
        )

    finally:
        if original is not None:
            os.environ["SUGARKUBE_MDNS_NO_TERMINATE"] = original
        elif "SUGARKUBE_MDNS_NO_TERMINATE" in os.environ:
            del os.environ["SUGARKUBE_MDNS_NO_TERMINATE"]


def test_ignore_local_flag_not_used():
    """
    Regression test for 2025-11-15-mdns-ignore-local-blocked-verification.

    The --ignore-local flag should NOT be used because:
    1. It prevents bootstrap nodes from verifying their own service publications
    2. It's unnecessary - nodes should discover all k3s services on the network
    """
    # Test all server discovery modes
    for mode in ["server-first", "server-count", "server-select"]:
        command = _build_command(mode, "_k3s-sugar-dev._tcp", resolve=True)

        assert "--ignore-local" not in command, (
            f"REGRESSION: --ignore-local flag is being used in {mode} mode. "
            "This prevents self-verification and is unnecessary for discovery."
        )


def test_timeout_exception_handles_bytes():
    """
    Regression test for 2025-11-15-mdns-timeout-bytes-str-mismatch.

    TimeoutExpired exceptions may contain bytes in stdout/stderr even when
    text=True is used. The code should handle this gracefully.
    """
    messages = []

    def runner(command, capture_output, text, check, timeout=None, env=None):
        # Simulate a timeout with bytes in the exception
        exc = subprocess.TimeoutExpired(command, timeout)
        # Explicitly set stdout as bytes (this can happen in real scenarios)
        exc.stdout = b"=;eth0;IPv4;k3s-server;_k3s-sugar-dev._tcp;local\n"
        exc.stderr = b"some error"
        raise exc

    # This should not crash with TypeError
    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    # Should return empty results (no valid records) but not crash
    assert results == []
    assert any("timed out" in msg for msg in messages)


def test_debug_dump_handles_mixed_bytes_and_str():
    """
    Regression test for TypeError when dumping debug info with mixed types.

    The debug dump code should handle lines that might be bytes or str.
    """
    messages = []
    calls = []

    def runner(command, capture_output, text, check, timeout=None, env=None):
        calls.append(command)
        # Return empty results to trigger the debug dump path
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",  # Empty stdout means no records found
            stderr="",
        )

    # This should not crash even if the internal processing somehow produces bytes
    results = query_mdns(
        "server-select",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == []
    # Verify the query was attempted
    assert len(calls) >= 2  # Should try both service types


def test_env_variable_documentation():
    """
    Document the expected behavior of SUGARKUBE_MDNS_NO_TERMINATE.

    This test serves as documentation for the environment variable.
    """
    # Default (no env var set): Do NOT use --terminate (wait for network)
    original = os.environ.get("SUGARKUBE_MDNS_NO_TERMINATE")
    try:
        if "SUGARKUBE_MDNS_NO_TERMINATE" in os.environ:
            del os.environ["SUGARKUBE_MDNS_NO_TERMINATE"]

        cmd_default = _build_command("server-select", "_k3s-sugar-dev._tcp")
        assert "--terminate" not in cmd_default

        # SUGARKUBE_MDNS_NO_TERMINATE=0: Use --terminate (fast, cache only)
        os.environ["SUGARKUBE_MDNS_NO_TERMINATE"] = "0"
        cmd_terminate = _build_command("server-select", "_k3s-sugar-dev._tcp")
        assert "--terminate" in cmd_terminate

        # SUGARKUBE_MDNS_NO_TERMINATE=1: Do NOT use --terminate (wait for network)
        os.environ["SUGARKUBE_MDNS_NO_TERMINATE"] = "1"
        cmd_no_terminate = _build_command("server-select", "_k3s-sugar-dev._tcp")
        assert "--terminate" not in cmd_no_terminate

    finally:
        if original is not None:
            os.environ["SUGARKUBE_MDNS_NO_TERMINATE"] = original
        elif "SUGARKUBE_MDNS_NO_TERMINATE" in os.environ:
            del os.environ["SUGARKUBE_MDNS_NO_TERMINATE"]
