import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_warns_when_avahi_systemd_unit_disabled(tmp_path) -> None:
    systemctl_stub = tmp_path / "systemctl"
    systemctl_stub.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "is-enabled" ]; then
  exit 1
fi

exit 0
""",
        encoding="utf-8",
    )
    systemctl_stub.chmod(0o755)

    env = {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SUGARKUBE_ENV": "dev",
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_TOKEN": "dummy",
    }

    result = subprocess.run(
        ["bash", str(SCRIPT), "--test-avahi-systemd-check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "systemd unit disabled; enable for reliable discovery" in result.stderr
    assert "unit=avahi-daemon" in result.stderr
