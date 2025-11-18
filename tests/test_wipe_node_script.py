import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wipe_node.sh"


@pytest.mark.parametrize("cluster, env", [("sweet", "test")])
def test_wipe_dry_run_reports_actions(tmp_path, cluster, env):
    env_vars = os.environ.copy()
    env_vars.update(
        {
            "ALLOW_NON_ROOT": "1",
            "DRY_RUN": "1",
            "SUGARKUBE_CLUSTER": cluster,
            "SUGARKUBE_ENV": env,
            "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
            "PATH": env_vars.get("PATH", ""),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env_vars,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    assert f"Selected cluster={cluster}" in stdout
    assert f"env={env}" in stdout
    assert "k3s-uninstall.sh" in stdout or "Skipping k3s-uninstall.sh" in stdout
    assert "k3s-agent-uninstall.sh" in stdout or "Skipping k3s-agent-uninstall.sh" in stdout
    assert "/etc/avahi/services/k3s-" in stdout
    assert "cleanup-mdns" in stdout


def test_wipe_invokes_uninstallers_when_available(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log_file = tmp_path / "calls.log"

    sudo_stub = fakebin / "sudo"
    sudo_stub.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nexec "$@"\n',
        encoding="utf-8",
    )
    sudo_stub.chmod(0o755)

    def write_stub(name: str) -> None:
        script_path = fakebin / name
        script_path.write_text(
            f"#!/usr/bin/env bash\nset -euo pipefail\n"
            f"printf '%s\\n' '{name}' >> '{log_file}'\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)

    for stub in (
        "k3s-uninstall.sh",
        "k3s-killall.sh",
        "k3s-agent-uninstall.sh",
    ):
        write_stub(stub)

    env_vars = os.environ.copy()
    env_vars.update(
        {
            "ALLOW_NON_ROOT": "1",
            "DRY_RUN": "0",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
            "PATH": f"{fakebin}:{env_vars.get('PATH', '')}",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env_vars,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    logged = log_file.read_text(encoding="utf-8").splitlines()
    for expected in (
        "k3s-killall.sh",
        "k3s-uninstall.sh",
        "k3s-agent-uninstall.sh",
    ):
        assert expected in logged
    assert "removed-dynamic: _k3s-sugar-dev._tcp" in result.stdout


def test_wipe_removes_join_gate_state_files(tmp_path):
    """Test that wipe removes join-gate state files for reproducible builds"""
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

    # Create a join-gate state file
    state_file = runtime_dir / "join-gate-sugar-dev.state"
    state_file.write_text("pid=1234\nhost=testhost\nowner=test-uuid\nport=12345\n")

    fakebin = tmp_path / "bin"
    fakebin.mkdir()

    sudo_stub = fakebin / "sudo"
    sudo_stub.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nexec "$@"\n',
        encoding="utf-8",
    )
    sudo_stub.chmod(0o755)

    env_vars = os.environ.copy()
    env_vars.update(
        {
            "ALLOW_NON_ROOT": "1",
            "DRY_RUN": "0",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
            "PATH": f"{fakebin}:{env_vars.get('PATH', '')}",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env_vars,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    # State file should be removed
    assert not state_file.exists(), "join-gate state file should be removed"

    # Should log the cleanup
    assert "removed-join-gate-state:" in result.stdout or "runtime-dir" in result.stdout


def test_wipe_dry_run_reports_join_gate_cleanup(tmp_path):
    """Test that dry run reports join-gate cleanup actions"""
    runtime_dir = tmp_path / "run"
    runtime_dir.mkdir()

    # Create a join-gate state file
    state_file = runtime_dir / "join-gate-sweet-test.state"
    state_file.write_text("pid=5678\nhost=dryrunhost\n")

    env_vars = os.environ.copy()
    env_vars.update(
        {
            "ALLOW_NON_ROOT": "1",
            "DRY_RUN": "1",
            "SUGARKUBE_CLUSTER": "sweet",
            "SUGARKUBE_ENV": "test",
            "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
            "PATH": env_vars.get("PATH", ""),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env_vars,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    # State file should NOT be removed in dry run
    assert state_file.exists(), "dry run should not remove files"

    # Should report what would be done
    assert "runtime" in result.stdout.lower() or "DRY_RUN" in result.stdout


def test_wipe_handles_missing_runtime_dir_gracefully(tmp_path):
    """Test that wipe handles missing runtime directory without error"""
    runtime_dir = tmp_path / "run" / "nonexistent"

    env_vars = os.environ.copy()
    env_vars.update(
        {
            "ALLOW_NON_ROOT": "1",
            "DRY_RUN": "0",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_RUNTIME_DIR": str(runtime_dir),
            "PATH": env_vars.get("PATH", ""),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env_vars,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "runtime-dir:not-found" in result.stdout or "Completed wipe" in result.stdout
