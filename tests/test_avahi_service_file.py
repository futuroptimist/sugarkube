from __future__ import annotations

import os
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def avahi_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()

    sudo_stub = stub_dir / "sudo"
    sudo_stub.write_text(
        """#!/usr/bin/env bash
if [ $# -eq 0 ]; then
  exit 0
fi
exec "$@"
""",
        encoding="utf-8",
    )
    sudo_stub.chmod(0o755)

    systemctl_stub = stub_dir / "systemctl"
    systemctl_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl_stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env.setdefault("SUGARKUBE_CLUSTER", "sugar")
    env.setdefault("SUGARKUBE_ENV", "dev")

    service_dir = tmp_path / "services"
    service_dir.mkdir()
    service_file = service_dir / "k3s-sugar-dev.service"
    return env, service_file


def test_service_file_is_valid_xml(avahi_env: tuple[dict[str, str], Path]) -> None:
    env, service_file = avahi_env
    extra_record = "note=sugar & spice"
    command = " ".join(
        [
            f"source {shlex.quote(str(SCRIPT))}",
            "&&",
            f"AVAHI_SERVICE_FILE={shlex.quote(str(service_file))}",
            "publish_avahi_service",
            "server",
            "6443",
            shlex.quote("leader=pi1.local"),
            shlex.quote("state=ready"),
            shlex.quote(extra_record),
        ]
    )
    subprocess.run(
        ["bash", "-c", command],
        env=env,
        check=True,
    )

    tree = ET.parse(service_file)
    root = tree.getroot()

    port = root.find("./service/port")
    assert port is not None
    assert port.text == "6443"

    records = [node.text for node in root.findall("./service/txt-record")]
    assert "k3s=1" in records
    assert "cluster=sugar" in records
    assert "env=dev" in records
    assert "role=server" in records
    assert "leader=pi1.local" in records
    assert "state=ready" in records
    assert extra_record in records
