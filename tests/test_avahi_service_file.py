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
    sudo.write_text("#!/usr/bin/env bash\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(0o755)

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_SERVERS": "1",
            "SUGARKUBE_NODE_TOKEN_PATH": str(tmp_path / "node-token"),
            "SUGARKUBE_BOOT_TOKEN_PATH": str(tmp_path / "boot-token"),
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
        }
    )
    return env


def test_publish_avahi_service_creates_valid_xml(avahi_env):
    env = dict(avahi_env)
    extra_records = ["leader=sugar-control-0", "special=ctrl & co"]

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--render-avahi-service",
            "server",
            "6443",
            *extra_records,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    service_dir = Path(env["SUGARKUBE_AVAHI_SERVICE_DIR"])
    service_file = service_dir / "k3s-sugar-dev.service"

    xml_text = service_file.read_text(encoding="utf-8")
    assert "<?xml version=\"1.0\"" in xml_text
    assert "<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">" in xml_text

    root = ET.fromstring(xml_text)

    name = root.find("name")
    assert name is not None
    assert name.text == "k3s API sugar/dev on %h"

    port = root.find(".//port")
    assert port is not None
    assert port.text == "6443"

    txt_records = [elem.text for elem in root.findall(".//txt-record")]
    assert "k3s=1" in txt_records
    assert "cluster=sugar" in txt_records
    assert "env=dev" in txt_records
    assert "role=server" in txt_records
    assert "leader=sugar-control-0" in txt_records
    assert "special=ctrl & co" in txt_records

