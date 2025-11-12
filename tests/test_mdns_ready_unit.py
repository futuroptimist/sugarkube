"""Unit tests for mdns_ready.sh wrapper function.

These tests verify the mdns_ready() function's D-Bus failure handling
and CLI fallback behavior with mocked tools.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MDNS_READY_SCRIPT = SCRIPTS_DIR / "mdns_ready.sh"


@pytest.fixture
def mock_env(tmp_path):
    """Set up a temporary environment with mocked binaries."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    # Create mock Python3 that just passes through to real python3
    real_python = subprocess.run(
        ["which", "python3"], capture_output=True, text=True, check=True
    ).stdout.strip()
    
    mock_python = bin_dir / "python3"
    mock_python.write_text(f"#!/bin/bash\nexec {real_python} \"$@\"\n")
    mock_python.chmod(0o755)
    
    return {
        "bin_dir": bin_dir,
        "path": f"{bin_dir}:{os.environ['PATH']}",
    }


def test_mdns_ready_dbus_failure_cli_success(mock_env):
    """Test that mdns_ready falls back to CLI when D-Bus fails.
    
    This test forces a D-Bus failure by mocking gdbus to return an error,
    and verifies that the CLI fallback path (avahi-browse) succeeds.
    """
    bin_dir = mock_env["bin_dir"]
    
    # Mock gdbus to fail (D-Bus unavailable)
    gdbus_mock = bin_dir / "gdbus"
    gdbus_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Error: Method GetVersionString unavailable' >&2\n"
        "exit 1\n"
    )
    gdbus_mock.chmod(0o755)
    
    # Mock avahi-browse to succeed with valid output
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo '=;eth0;IPv4;test-service;_k3s-sugar-dev._tcp;local'\n"
        "exit 0\n"
    )
    avahi_browse_mock.chmod(0o755)
    
    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_TIMEOUT_MS"] = "500"
    
    result = subprocess.run(
        [str(MDNS_READY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    
    # Assert CLI fallback succeeded
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\n{result.stderr}"
    
    output = result.stdout + result.stderr
    
    # Verify CLI method was used (not D-Bus)
    assert "method=cli" in output, f"Expected method=cli in output\n{output}"
    
    # Verify successful outcome
    assert "outcome=ok" in output, f"Expected outcome=ok in output\n{output}"
    
    # Verify D-Bus fallback flag is set
    assert "dbus_fallback=true" in output, (
        f"Expected dbus_fallback=true indicating D-Bus was tried first\n{output}"
    )
    
    # Verify D-Bus status shows it failed
    assert "dbus_status=" in output, f"Expected dbus_status in output\n{output}"
    
    # Verify browse command is logged
    assert "browse_command=" in output, f"Expected browse_command in output\n{output}"
    
    # Verify structured logging contains required fields
    assert "event=mdns_ready" in output, f"Expected event=mdns_ready in output\n{output}"
    assert "elapsed_ms=" in output, f"Expected elapsed_ms in output\n{output}"


def test_mdns_ready_dbus_and_cli_both_fail(mock_env):
    """Test that mdns_ready fails when both D-Bus and CLI fail.
    
    This ensures proper error handling when no fallback is available.
    """
    bin_dir = mock_env["bin_dir"]
    
    # Mock gdbus to fail
    gdbus_mock = bin_dir / "gdbus"
    gdbus_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Error: D-Bus connection failed' >&2\n"
        "exit 1\n"
    )
    gdbus_mock.chmod(0o755)
    
    # Mock avahi-browse to also fail
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Error: Daemon not running' >&2\n"
        "exit 2\n"
    )
    avahi_browse_mock.chmod(0o755)
    
    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_TIMEOUT_MS"] = "500"
    
    result = subprocess.run(
        [str(MDNS_READY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    
    # Assert it fails
    assert result.returncode == 1, f"Expected exit code 1, got {result.returncode}"
    
    output = result.stdout + result.stderr
    
    # Verify failure is reported
    assert "outcome=fail" in output, f"Expected outcome=fail in output\n{output}"
    
    # Verify CLI method was attempted
    assert "method=cli" in output, f"Expected method=cli in output\n{output}"
    
    # Verify both status codes are logged
    assert "dbus_status=" in output, f"Expected dbus_status in output\n{output}"
    assert "cli_status=" in output, f"Expected cli_status in output\n{output}"


def test_mdns_ready_cli_no_output(mock_env):
    """Test that mdns_ready fails when CLI succeeds but returns no output.
    
    This tests the edge case where avahi-browse exits 0 but has no services.
    """
    bin_dir = mock_env["bin_dir"]
    
    # Mock gdbus to fail
    gdbus_mock = bin_dir / "gdbus"
    gdbus_mock.write_text(
        "#!/usr/bin/env bash\n"
        "exit 1\n"
    )
    gdbus_mock.chmod(0o755)
    
    # Mock avahi-browse to succeed but return no output
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n"
        "# No output - no services found\n"
        "exit 0\n"
    )
    avahi_browse_mock.chmod(0o755)
    
    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_TIMEOUT_MS"] = "500"
    
    result = subprocess.run(
        [str(MDNS_READY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    
    # Assert it fails due to no output
    assert result.returncode == 1, f"Expected exit code 1, got {result.returncode}"
    
    output = result.stdout + result.stderr
    
    # Verify no_output outcome
    assert "outcome=no_output" in output, f"Expected outcome=no_output in output\n{output}"
    assert "lines=0" in output, f"Expected lines=0 in output\n{output}"


def test_mdns_ready_dbus_success(mock_env):
    """Test that mdns_ready succeeds via D-Bus when available.
    
    This verifies the primary (non-fallback) code path.
    """
    bin_dir = mock_env["bin_dir"]
    
    # Mock gdbus to succeed
    gdbus_mock = bin_dir / "gdbus"
    gdbus_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"('avahi-daemon 0.8')\"\n"
        "exit 0\n"
    )
    gdbus_mock.chmod(0o755)
    
    # Mock avahi-browse (should not be called)
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'ERROR: Should not be called when D-Bus succeeds' >&2\n"
        "exit 1\n"
    )
    avahi_browse_mock.chmod(0o755)
    
    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_TIMEOUT_MS"] = "500"
    
    result = subprocess.run(
        [str(MDNS_READY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    
    # Assert D-Bus path succeeded
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\n{result.stderr}"
    
    output = result.stdout + result.stderr
    
    # Verify D-Bus method was used (not CLI)
    assert "method=dbus" in output, f"Expected method=dbus in output\n{output}"
    
    # Verify successful outcome
    assert "outcome=ok" in output, f"Expected outcome=ok in output\n{output}"
    
    # Verify no fallback flag (D-Bus worked)
    assert "dbus_fallback=true" not in output, (
        f"Should not have dbus_fallback=true when D-Bus succeeds\n{output}"
    )
