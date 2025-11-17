"""
Regression test for node-token creation after bootstrap.

This test verifies that when `just up dev` is run without SUGARKUBE_TOKEN_DEV
(bootstrap mode), the node-token file is created and available for users to
retrieve and use on subsequent nodes.

Related to hostname collision and mDNS issues preventing node-token creation.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def create_mock_k3s_install(bin_dir: Path, node_token_dir: Path) -> Path:
    """
    Create a mock k3s install script that:
    1. Creates the k3s service
    2. Writes the node-token file after a brief delay (simulating k3s async behavior)
    """
    k3s_install = bin_dir / "mock-k3s-install.sh"
    node_token_path = node_token_dir / "node-token"
    
    k3s_install.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            
            # Mock k3s installation
            echo "Mock k3s install called with: $*" >&2
            
            # Simulate k3s server starting and creating node-token file asynchronously
            # In real k3s, this file is created after the service starts, not immediately
            (
              sleep 2  # Simulate the delay before k3s creates the token file
              mkdir -p "{node_token_dir}"
              echo "K10abc123mock456token789xyz" > "{node_token_path}"
              chmod 600 "{node_token_path}"
            ) &
            
            exit 0
            """
        ),
        encoding="utf-8",
    )
    k3s_install.chmod(0o755)
    return k3s_install


def create_mock_check_apiready(bin_dir: Path) -> Path:
    """Create a mock check_apiready.sh that always succeeds."""
    check_apiready = bin_dir / "check_apiready.sh"
    check_apiready.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Mock API readiness check - always returns success
            echo "api_ready=true"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    check_apiready.chmod(0o755)
    return check_apiready


def create_minimal_mocks(bin_dir: Path, script_dir: Path) -> None:
    """Create minimal mocks for required dependencies."""
    # Mock systemctl
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    
    # Mock avahi-browse
    avahi_browse = bin_dir / "avahi-browse"
    avahi_browse.write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    avahi_browse.chmod(0o755)
    
    # Mock configure_avahi.sh
    configure_avahi = script_dir / "configure_avahi.sh"
    configure_avahi.write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    configure_avahi.chmod(0o755)


@pytest.fixture
def mock_env(tmp_path):
    """Set up mock environment for testing bootstrap."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    
    node_token_dir = tmp_path / "var" / "lib" / "rancher" / "k3s" / "server"
    node_token_dir.mkdir(parents=True)
    
    k3s_install = create_mock_k3s_install(bin_dir, node_token_dir)
    check_apiready = create_mock_check_apiready(bin_dir)
    create_minimal_mocks(bin_dir, script_dir)
    
    avahi_service_dir = tmp_path / "avahi" / "services"
    avahi_service_dir.mkdir(parents=True)
    
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "1",  # Single server bootstrap
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_K3S_INSTALL_SCRIPT": str(k3s_install),
            "SUGARKUBE_API_READY_CHECK_BIN": str(check_apiready),
            "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(script_dir / "configure_avahi.sh"),
            "SUGARKUBE_NODE_TOKEN_PATH": str(node_token_dir / "node-token"),
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(avahi_service_dir),
            "SUGARKUBE_SKIP_SYSTEMCTL": "1",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_NODE_TOKEN_TIMEOUT": "10",  # 10 second timeout for test
            "SUGARKUBE_NODE_TOKEN_POLL_INTERVAL": "0.5",  # Check every 0.5s
            "SUGARKUBE_CONFIGURE_AVAHI": "0",  # Skip avahi configuration
            "SUGARKUBE_SKIP_ABSENCE_GATE": "1",  # Skip absence gate
        }
    )
    
    return env, node_token_dir


def test_bootstrap_creates_node_token_single_server(mock_env):
    """
    Test that bootstrapping a single-server cluster waits for and verifies
    the node-token file exists after installation.
    """
    env, node_token_dir = mock_env
    node_token_path = node_token_dir / "node-token"
    
    # Run k3s-discover in bootstrap mode (no token set)
    result = subprocess.run(
        ["bash", SCRIPT],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    
    # Check that the script succeeded
    assert result.returncode == 0, (
        f"k3s-discover.sh failed:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    
    # Verify the node-token file was created
    assert node_token_path.exists(), (
        f"node-token file not found at {node_token_path}\n"
        f"Script output:\n{result.stderr}"
    )
    
    # Verify file has content
    token_content = node_token_path.read_text().strip()
    assert token_content, "node-token file is empty"
    assert token_content.startswith("K10"), f"Invalid token format: {token_content}"
    
    # Verify logging indicates node token was waited for
    assert "node_token_wait" in result.stderr or "node_token_ready" in result.stderr, (
        "No evidence of waiting for node-token in logs"
    )


def test_bootstrap_creates_node_token_cluster_init(mock_env):
    """
    Test that bootstrapping with cluster-init (HA mode) waits for and verifies
    the node-token file exists after installation.
    """
    env, node_token_dir = mock_env
    env["SUGARKUBE_SERVERS"] = "3"  # HA cluster mode
    node_token_path = node_token_dir / "node-token"
    
    # Run k3s-discover in bootstrap mode (no token set)
    result = subprocess.run(
        ["bash", SCRIPT],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    
    # Check that the script succeeded
    assert result.returncode == 0, (
        f"k3s-discover.sh failed:\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    
    # Verify the node-token file was created
    assert node_token_path.exists(), (
        f"node-token file not found at {node_token_path}\n"
        f"Script output:\n{result.stderr}"
    )
    
    # Verify file has content
    token_content = node_token_path.read_text().strip()
    assert token_content, "node-token file is empty"
    assert token_content.startswith("K10"), f"Invalid token format: {token_content}"


def test_bootstrap_timeout_if_node_token_not_created(tmp_path):
    """
    Test that bootstrap fails with clear error if node-token is never created.
    This ensures users get actionable feedback rather than silent failures.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    
    node_token_dir = tmp_path / "var" / "lib" / "rancher" / "k3s" / "server"
    node_token_dir.mkdir(parents=True)
    
    # Create k3s install script that NEVER creates the token file
    k3s_install = bin_dir / "mock-k3s-install-broken.sh"
    k3s_install.write_text(
        "#!/usr/bin/env bash\necho 'Mock k3s install (no token)' >&2\nexit 0\n",
        encoding="utf-8",
    )
    k3s_install.chmod(0o755)
    
    check_apiready = create_mock_check_apiready(bin_dir)
    
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    create_minimal_mocks(bin_dir, script_dir)
    
    avahi_service_dir = tmp_path / "avahi" / "services"
    avahi_service_dir.mkdir(parents=True)
    
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "1",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_K3S_INSTALL_SCRIPT": str(k3s_install),
            "SUGARKUBE_API_READY_CHECK_BIN": str(check_apiready),
            "SUGARKUBE_NODE_TOKEN_PATH": str(node_token_dir / "node-token"),
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(avahi_service_dir),
            "SUGARKUBE_SKIP_SYSTEMCTL": "1",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_NODE_TOKEN_TIMEOUT": "5",  # Short timeout for test
            "SUGARKUBE_NODE_TOKEN_POLL_INTERVAL": "0.5",
            "SUGARKUBE_CONFIGURE_AVAHI": "0",  # Skip avahi configuration
            "SUGARKUBE_SKIP_ABSENCE_GATE": "1",  # Skip absence gate
        }
    )
    
    result = subprocess.run(
        ["bash", SCRIPT],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    
    # Script should fail
    assert result.returncode != 0, "Script should fail when node-token is not created"
    
    # Error message should be clear
    assert "Node token file not created" in result.stderr, (
        "Error message should explain that node-token was not created"
    )
