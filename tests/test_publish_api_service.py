import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def avahi_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    sudo = bin_dir / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nif [[ \"$1\" == \"-n\" ]]; then\n  shift\nfi\nexec \"$@\"\n",
        encoding="utf-8",
    )
    sudo.chmod(0o755)

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
        }
    )
    return env


def test_publish_api_service_renders_xml(avahi_env):
    env = dict(avahi_env)
    result = subprocess.run(
        ["bash", str(SCRIPT), "--render-avahi-service", "server"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    service_dir = Path(env["SUGARKUBE_AVAHI_SERVICE_DIR"])
    service_file = service_dir / "k3s-sugar-dev.service"
    assert service_file.exists()

    tree = ET.parse(service_file)
    root = tree.getroot()

    records = [elem.text for elem in root.findall(".//txt-record")]
    assert "k3s=1" in records
    assert "cluster=sugar" in records
    assert "env=dev" in records
    assert "role=server" in records

    port = root.find(".//port")
    assert port is not None and port.text == "6443"
