import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wipe_node.sh"


@pytest.mark.parametrize(
    "cluster, env_name",
    [
        ("sugar", "dev"),
        ("orchard", "test"),
    ],
)
def test_wipe_dry_run_reports_targets(cluster, env_name):
    env = os.environ.copy()
    env.update(
        {
            "DRY_RUN": "1",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": cluster,
            "SUGARKUBE_ENV": env_name,
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    assert f"Selected cluster={cluster} env={env_name}" in stdout
    assert "/etc/avahi/services/k3s-" in stdout
    assert "Skipping k3s-uninstall.sh" in stdout or "[dry-run] sudo -n" in stdout
    assert "Completed wipe" in stdout


def test_wipe_dry_run_lists_uninstallers(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log_path = tmp_path / "calls.log"

    for name in (
        "k3s-uninstall.sh",
        "k3s-killall.sh",
        "k3s-agent-uninstall.sh",
    ):
        stub = fakebin / name
        stub.write_text(
            f"#!/usr/bin/env bash\nset -euo pipefail\necho {name} >> '{log_path}'\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env.get('PATH', '')}",
            "DRY_RUN": "1",
            "ALLOW_NON_ROOT": "1",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    for name in (
        "k3s-killall.sh",
        "k3s-uninstall.sh",
        "k3s-agent-uninstall.sh",
    ):
        path = fakebin / name
        assert f"Found {name} at {path}" in stdout
        assert f"[dry-run] sudo -n {path} || {path}" in stdout
