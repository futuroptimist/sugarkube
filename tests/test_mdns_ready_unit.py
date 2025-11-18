"""Unit tests for mdns_ready.sh wrapper function.

These tests verify the mdns_ready() function's D-Bus failure handling
and CLI fallback behavior with mocked tools.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MDNS_READY_SCRIPT = SCRIPTS_DIR / "mdns_ready.sh"


@pytest.fixture
def mock_env(tmp_path):
    """Set up a temporary environment with mocked binaries.

    Args:
        tmp_path (pathlib.Path): pytest's tmp_path fixture providing a temporary directory.

    Returns:
        dict: Environment configuration with keys:
            - bin_dir (pathlib.Path): Path to the mock binary directory.
            - path (str): Modified PATH with mock binaries prepended.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create mock Python3 that just passes through to real python3
    real_python = subprocess.run(
        ["which", "python3"], capture_output=True, text=True, check=True
    ).stdout.strip()

    mock_python = bin_dir / "python3"
    mock_python.write_text(f'#!/bin/bash\nexec {real_python} "$@"\n')
    mock_python.chmod(0o755)

    return {
        "bin_dir": bin_dir,
        "path": f"{bin_dir}:{os.environ['PATH']}",
    }


def test_mdns_ready_dbus_failure_cli_success(mock_env):
    """Test that mdns_ready falls back to CLI when D-Bus fails.

    This test forces a D-Bus failure by mocking busctl to return an error,
    and verifies that the CLI fallback path (avahi-browse) succeeds.
    """
    bin_dir = mock_env["bin_dir"]

    # Mock busctl to fail (D-Bus unavailable)
    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Error: D-Bus connection failed' >&2\n"
        "exit 1\n"
    )
    busctl_mock.chmod(0o755)

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
    env["AVAHI_DBUS_WAIT_MS"] = "100"  # Short wait for tests

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
    assert (
        "dbus_fallback=true" in output
    ), f"Expected dbus_fallback=true indicating D-Bus was tried first\n{output}"

    # Verify D-Bus status shows it failed
    assert "dbus_status=" in output, f"Expected dbus_status in output\n{output}"

    # Verify service type is logged
    assert "service_type=" in output, f"Expected service_type in output\n{output}"

    # Verify structured logging contains required fields
    assert "event=mdns_ready" in output, f"Expected event=mdns_ready in output\n{output}"
    assert "elapsed_ms=" in output, f"Expected elapsed_ms in output\n{output}"

    # Verify D-Bus failure log captured object/method/owner details
    assert "bus_method=NameHasOwner" in output, (
        f"Expected bus_method=NameHasOwner in D-Bus failure log\n{output}"
    )
    assert "bus_owner=absent" in output, (
        f"Expected bus_owner=absent when ownership timed out\n{output}"
    )


def test_mdns_ready_logs_dbus_method_failure_details(mock_env):
    """Ensure GetVersionString failures log object, interface, method, and owner."""

    bin_dir = mock_env["bin_dir"]

    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *\"NameHasOwner\"*)\n"
        "    echo 'b true'\n"
        "    exit 0\n"
        "    ;;\n"
        "  *\"get-property\"*)\n"
        "    exit 1\n"
        "    ;;\n"
        "  *\"GetVersionString\"*)\n"
        "    echo 'Call failed: Method GetVersionString unavailable' >&2\n"
        "    exit 1\n"
        "    ;;\n"
        "esac\n"
        "echo \"unexpected busctl call: $*\" >&2\n"
        "exit 2\n"
    )
    busctl_mock.chmod(0o755)

    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo '=;eth0;IPv4;test-service;_k3s-sugar-dev._tcp;local'\n"
        "exit 0\n"
    )
    avahi_browse_mock.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_WAIT_MS"] = "200"

    result = subprocess.run(
        [str(MDNS_READY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}\n{result.stderr}"
    )

    output = result.stdout + result.stderr

    assert "event=mdns_ready_dbus" in output, (
        f"Expected D-Bus failure log to include event=mdns_ready_dbus\n{output}"
    )
    assert "bus_object=/org/freedesktop/Avahi/Server" in output, f"Expected bus_object=/org/freedesktop/Avahi/Server in failure log\n{output}"
    assert "bus_interface=org.freedesktop.Avahi.Server" in output, (
        f"Expected bus_interface in failure log\n{output}"
    )
    assert "bus_method=GetVersionString" in output, (
        f"Expected bus_method=GetVersionString in failure log\n{output}"
    )
    assert "bus_owner=owned" in output, f"Expected bus_owner=owned in failure log\n{output}"


def test_mdns_ready_dbus_and_cli_both_fail(mock_env):
    """Test that mdns_ready fails when both D-Bus and CLI fail.

    This ensures proper error handling when no fallback is available.
    """
    bin_dir = mock_env["bin_dir"]

    # Mock busctl to fail
    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text(
        "#!/usr/bin/env bash\n" "echo 'Error: D-Bus connection failed' >&2\n" "exit 1\n"
    )
    busctl_mock.chmod(0o755)

    # Mock avahi-browse to also fail
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n" "echo 'Error: Daemon not running' >&2\n" "exit 2\n"
    )
    avahi_browse_mock.chmod(0o755)

    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_WAIT_MS"] = "100"  # Short wait for tests

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

    # Verify structured logging
    assert "event=mdns_ready" in output, f"Expected event=mdns_ready in output\n{output}"


def test_mdns_ready_cli_no_output(mock_env):
    """Test that mdns_ready fails when CLI succeeds but returns no output.

    This tests the edge case where avahi-browse exits 0 but has no services.
    """
    bin_dir = mock_env["bin_dir"]

    # Mock busctl to fail
    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text("#!/usr/bin/env bash\n" "exit 1\n")
    busctl_mock.chmod(0o755)

    # Mock avahi-browse to succeed but return no output
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n" "# No output - no services found\n" "exit 0\n"
    )
    avahi_browse_mock.chmod(0o755)

    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_WAIT_MS"] = "100"  # Short wait for tests

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

    # Verify timeout outcome (CLI succeeded but no services)
    assert "outcome=timeout" in output, f"Expected outcome=timeout in output\n{output}"
    assert "event=mdns_ready" in output, f"Expected event=mdns_ready in output\n{output}"


def test_mdns_ready_dbus_success(mock_env):
    """Test that mdns_ready succeeds via D-Bus when available.

    This verifies the primary (non-fallback) code path with busctl.
    """
    bin_dir = mock_env["bin_dir"]

    # Mock busctl to succeed for both NameHasOwner and GetVersionString
    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text(
        "#!/usr/bin/env bash\n"
        "# Succeed for both NameHasOwner check and GetVersionString call\n"
        "exit 0\n"
    )
    busctl_mock.chmod(0o755)

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
    env["AVAHI_DBUS_WAIT_MS"] = "5000"

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
    assert (
        "dbus_fallback=true" not in output
    ), f"Should not have dbus_fallback=true when D-Bus succeeds\n{output}"

    # Verify structured logging
    assert "event=mdns_ready" in output, f"Expected event=mdns_ready in output\n{output}"
    assert "elapsed_ms=" in output, f"Expected elapsed_ms in output\n{output}"


def test_mdns_ready_dbus_late_but_succeeds(mock_env):
    """Test that mdns_ready retries and succeeds when D-Bus ownership arrives late.

    This simulates a cold start where Avahi takes a few attempts to register
    its D-Bus name, but eventually succeeds.
    """
    bin_dir = mock_env["bin_dir"]

    # Create a state file to track call count
    state_file = bin_dir / "busctl_call_count"
    state_file.write_text("0")

    # Mock busctl to fail first 2 times, then succeed
    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text(
        f"""#!/usr/bin/env bash
# Track number of calls
state_file="{state_file}"
count=$(cat "$state_file")
count=$((count + 1))
echo "$count" > "$state_file"

# Fail first 2 NameHasOwner calls (simulating Avahi ownership not registered yet)
if [ "$count" -le 2 ]; then
    exit 1
fi

# Succeed on subsequent calls (3rd NameHasOwner check, then GetVersionString)
exit 0
"""
    )
    busctl_mock.chmod(0o755)

    # Mock avahi-browse (should not be called if D-Bus eventually succeeds)
    avahi_browse_mock = bin_dir / "avahi-browse"
    avahi_browse_mock.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'ERROR: Should not be called when D-Bus eventually succeeds' >&2\n"
        "exit 1\n"
    )
    avahi_browse_mock.chmod(0o755)

    # Run mdns_ready.sh with mocked environment
    env = os.environ.copy()
    env["PATH"] = mock_env["path"]
    env["AVAHI_DBUS_WAIT_MS"] = "5000"  # Allow enough time for retries

    result = subprocess.run(
        [str(MDNS_READY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    # Assert D-Bus path succeeded after retries
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\n{result.stderr}"

    output = result.stdout + result.stderr

    # Verify D-Bus method was used (not CLI)
    assert "method=dbus" in output, f"Expected method=dbus in output\n{output}"

    # Verify successful outcome
    assert "outcome=ok" in output, f"Expected outcome=ok in output\n{output}"

    # Verify multiple ownership attempts were made
    assert "ownership_attempts=" in output, f"Expected ownership_attempts in output\n{output}"

    # Verify structured logging
    assert "event=mdns_ready" in output, f"Expected event=mdns_ready in output\n{output}"
    assert "elapsed_ms=" in output, f"Expected elapsed_ms in output\n{output}"

    # Verify busctl was called multiple times (NameHasOwner checks + GetVersionString)
    final_count = int(state_file.read_text())
    assert final_count >= 3, (
        f"Expected at least 3 total busctl calls "
        f"(including both NameHasOwner checks and the final GetVersionString call), "
        f"got {final_count}"
    )
