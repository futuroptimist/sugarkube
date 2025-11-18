import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def mdns_diag_script():
    script = SCRIPTS_DIR / "mdns_diag.sh"
    assert script.exists(), f"mdns_diag.sh not found at {script}"
    assert script.is_file(), f"mdns_diag.sh is not a file at {script}"
    # Check if executable
    if not script.stat().st_mode & 0o111:
        pytest.skip("mdns_diag.sh is not executable")
    return script


def test_mdns_diag_help_flag(mdns_diag_script):
    """Test that mdns_diag.sh --help displays usage information."""
    result = subprocess.run(
        [str(mdns_diag_script), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}"
    assert "Usage:" in result.stdout, "Help output should contain 'Usage:'"
    assert "--hostname" in result.stdout, "Help should mention --hostname option"
    assert "--service-type" in result.stdout, "Help should mention --service-type option"


def test_mdns_diag_invalid_option(mdns_diag_script):
    """Test that mdns_diag.sh rejects invalid options."""
    result = subprocess.run(
        [str(mdns_diag_script), "--invalid-option"],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2, f"Expected exit code 2 for invalid option, got {result.returncode}"
    assert "ERROR:" in result.stderr, "Error message should be printed to stderr"


def test_mdns_diag_hostname_option(mdns_diag_script):
    """Test that mdns_diag.sh accepts --hostname option."""
    try:
        result = subprocess.run(
            [str(mdns_diag_script), "--hostname", "testhost.local"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Script should run but may fail if services aren't available
        # We're just checking it accepts the option
        assert "Hostname: testhost.local" in result.stdout or "Hostname: testhost.local" in result.stderr
    except subprocess.TimeoutExpired:
        pytest.skip("avahi/mDNS not available or hanging in CI environment")


def test_mdns_diag_service_type_option(mdns_diag_script):
    """Test that mdns_diag.sh accepts --service-type option."""
    try:
        result = subprocess.run(
            [str(mdns_diag_script), "--service-type", "_test._tcp"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Script should run but may fail if services aren't available
        # We're just checking it accepts the option
        assert "Service:  _test._tcp" in result.stdout or "Service:  _test._tcp" in result.stderr
    except subprocess.TimeoutExpired:
        pytest.skip("avahi/mDNS not available or hanging in CI environment")


def test_mdns_diag_output_format(mdns_diag_script):
    """Test that mdns_diag.sh produces expected output format."""
    try:
        result = subprocess.run(
            [str(mdns_diag_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Check for expected output structure (regardless of success/failure)
        output = result.stdout + result.stderr
        assert "=== mDNS Diagnostic ===" in output, "Should have diagnostic header"
        assert "Hostname:" in output, "Should display hostname"
        assert "Service:" in output, "Should display service type"

        # Should have at least one check
        checks = ["Checking D-Bus", "Checking Avahi daemon", "Browsing for", "Resolving"]
        assert any(check in output for check in checks), "Should perform at least one check"
    except subprocess.TimeoutExpired:
        pytest.skip("avahi/mDNS not available or hanging in CI environment")


def test_mdns_diag_environment_variables(mdns_diag_script):
    """Test that mdns_diag.sh respects environment variables."""
    env = {
        "MDNS_DIAG_HOSTNAME": "envhost.local",
        "SUGARKUBE_CLUSTER": "testcluster",
        "SUGARKUBE_ENV": "testenv",
    }

    try:
        result = subprocess.run(
            [str(mdns_diag_script)],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, **env},
        )

        output = result.stdout + result.stderr
        assert "envhost.local" in output, "Should use MDNS_DIAG_HOSTNAME from environment"
        assert "_k3s-testcluster-testenv._tcp" in output, "Should use cluster and env from environment"
    except subprocess.TimeoutExpired:
        pytest.skip("avahi/mDNS not available or hanging in CI environment")


def test_mdns_diag_exit_codes(mdns_diag_script):
    """Test that mdns_diag.sh returns appropriate exit codes."""
    # With --help, should exit 0
    result = subprocess.run(
        [str(mdns_diag_script), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, "Help should exit with code 0"

    # With invalid option, should exit 2
    result = subprocess.run(
        [str(mdns_diag_script), "--invalid"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2, "Invalid option should exit with code 2"

    # Normal run may exit 0 or 1 depending on system state
    try:
        result = subprocess.run(
            [str(mdns_diag_script)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode in [0, 1], f"Normal run should exit with 0 or 1, got {result.returncode}"
    except subprocess.TimeoutExpired:
        pytest.skip("avahi/mDNS not available or hanging in CI environment")
