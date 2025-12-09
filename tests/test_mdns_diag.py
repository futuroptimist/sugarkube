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
    assert script.stat().st_mode & 0o111, "mdns_diag.sh must be executable"
    return script


def test_mdns_diag_script_is_tracked_executable(mdns_diag_script):
    """The diagnostic script should stay executable in git and on disk."""

    repo_root = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-s",
            str(mdns_diag_script.relative_to(repo_root)),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert tracked.stdout.startswith("100755"), "Tracked mode should preserve executability"


def _stub_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("MDNS_DIAG_HOSTNAME", "stub.local")
    env.setdefault("MDNS_DIAG_STUB_MODE", "1")
    env.update(overrides)
    return env


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

    assert result.returncode == 2, (
        "Expected exit code 2 for invalid option, got "
        f"{result.returncode}"
    )
    assert "ERROR:" in result.stderr, "Error message should be printed to stderr"


def test_mdns_diag_stub_mode_short_circuits_checks(mdns_diag_script):
    """Stub mode should exit quickly without Avahi tooling."""

    result = subprocess.run(
        [str(mdns_diag_script)],
        capture_output=True,
        text=True,
        timeout=5,
        env=_stub_env(MDNS_DIAG_HOSTNAME="speedy.local"),
    )

    assert result.returncode == 0
    assert "Stub mode enabled" in result.stdout
    assert "speedy.local" in result.stdout


def test_mdns_diag_hostname_option(mdns_diag_script):
    """Test that mdns_diag.sh accepts --hostname option."""

    result = subprocess.run(
        [str(mdns_diag_script), "--hostname", "testhost.local"],
        capture_output=True,
        text=True,
        timeout=5,
        env=_stub_env(),
    )

    assert result.returncode == 0
    assert "Hostname: testhost.local" in result.stdout


def test_mdns_diag_service_type_option(mdns_diag_script):
    """Test that mdns_diag.sh accepts --service-type option."""

    result = subprocess.run(
        [str(mdns_diag_script), "--service-type", "_test._tcp"],
        capture_output=True,
        text=True,
        timeout=5,
        env=_stub_env(),
    )

    assert result.returncode == 0
    assert "Service:  _test._tcp" in result.stdout


def test_mdns_diag_output_format(mdns_diag_script):
    """Test that mdns_diag.sh produces expected output format."""

    result = subprocess.run(
        [str(mdns_diag_script)],
        capture_output=True,
        text=True,
        timeout=5,
        env=_stub_env(),
    )

    output = result.stdout
    assert "=== mDNS Diagnostic ===" in output, "Should have diagnostic header"
    assert "Hostname:" in output, "Should display hostname"
    assert "Service:" in output, "Should display service type"
    assert "Stub mode enabled" in output, "Stub mode should log the short-circuit"


def test_mdns_diag_environment_variables(mdns_diag_script):
    """Test that mdns_diag.sh respects environment variables."""
    env = {
        "MDNS_DIAG_HOSTNAME": "envhost.local",
        "SUGARKUBE_CLUSTER": "testcluster",
        "SUGARKUBE_ENV": "testenv",
    }

    result = subprocess.run(
        [str(mdns_diag_script)],
        capture_output=True,
        text=True,
        timeout=5,
        env=_stub_env(**env),
    )

    output = result.stdout
    assert "envhost.local" in output, "Should use MDNS_DIAG_HOSTNAME from environment"
    assert "_k3s-testcluster-testenv._tcp" in output, "Should use cluster and env from environment"


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

    result = subprocess.run(
        [str(mdns_diag_script)],
        capture_output=True,
        text=True,
        timeout=5,
        env=_stub_env(),
    )
    assert result.returncode == 0, "Stub mode should exit with code 0"
