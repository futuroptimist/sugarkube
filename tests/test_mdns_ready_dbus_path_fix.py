"""Test for mdns_ready.sh D-Bus path fix.

This test verifies that mdns_ready.sh correctly uses /org/freedesktop/Avahi/Server
as the D-Bus object path instead of / when calling GetVersionString.
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
    """Set up a temporary environment with mocked binaries."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # Create mock Python3
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


def test_mdns_ready_uses_correct_dbus_path(mock_env):
    """Test that mdns_ready.sh uses the correct D-Bus object path.
    
    This test verifies the fix for the issue where mdns_ready.sh was using
    '/' instead of '/org/freedesktop/Avahi/Server' as the object path,
    causing GetVersionString calls to fail with "Method...doesn't exist" errors.
    """
    bin_dir = mock_env["bin_dir"]

    # Track what busctl was called with
    busctl_log = bin_dir / "busctl.log"
    
    # Mock busctl to log its arguments and handle both ownership and GetVersionString
    busctl_mock = bin_dir / "busctl"
    busctl_mock.write_text(
        f"""#!/usr/bin/env bash
echo "$@" >> {busctl_log}

# Handle NameHasOwner check (return success to allow GetVersionString call)
if [[ "$*" == *"NameHasOwner"* ]]; then
    echo "OWNERSHIP_CHECK: passed" >> {busctl_log}
    exit 0
fi

# Check if this is the GetVersionString call
if [[ "$*" == *"GetVersionString"* ]]; then
    # Log the object path argument
    echo "OBJECT_PATH: $5" >> {busctl_log}
    # Fail so it falls back to CLI
    echo 'Error: D-Bus test failure' >&2
    exit 1
fi

# Default: fail
exit 1
"""
    )
    busctl_mock.chmod(0o755)

    # Mock avahi-browse to succeed (CLI fallback)
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

    # Should succeed via CLI fallback
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\n{result.stderr}"

    # Check that busctl was called with the correct object path
    log_content = busctl_log.read_text()
    assert "/org/freedesktop/Avahi/Server" in log_content, (
        f"Expected busctl to be called with '/org/freedesktop/Avahi/Server' object path, "
        f"but log shows:\n{log_content}"
    )
    
    # Verify it's NOT using the wrong path
    # The log should contain the full busctl call including /org/freedesktop/Avahi/Server
    assert "OBJECT_PATH: /org/freedesktop/Avahi/Server" in log_content, (
        f"Expected busctl GetVersionString call to use /org/freedesktop/Avahi/Server, "
        f"but log shows:\n{log_content}"
    )

    # Verify output logs show correct path in error reporting
    output = result.stdout + result.stderr
    if "bus_object=" in output:
        assert "bus_object=/org/freedesktop/Avahi/Server" in output, (
            f"Expected log output to show bus_object=/org/freedesktop/Avahi/Server\n{output}"
        )
