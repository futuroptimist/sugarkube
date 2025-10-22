import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


def test_service_file_is_valid_xml(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl_stub = bin_dir / "systemctl"
    systemctl_stub.write_text("#!/bin/sh\nexit 0\n")
    systemctl_stub.chmod(0o755)

    service_file = tmp_path / "k3s.service"

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["SUGARKUBE_TOKEN"] = "dummy-token"
    env["SUGARKUBE_SUDO"] = ""
    env["SUGARKUBE_AVAHI_SERVICE_FILE"] = str(service_file)

    subprocess.run(
        [str(SCRIPT), "--publish-avahi-service", "server"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    tree = ET.parse(service_file)
    root = tree.getroot()

    assert root.tag == "service-group"

    name_elem = root.find("./name")
    assert name_elem is not None
    assert name_elem.text == "k3s API sugar/dev on %h"

    service_elem = root.find("./service")
    assert service_elem is not None

    port_elem = service_elem.find("./port")
    assert port_elem is not None
    assert port_elem.text == "6443"

    txt_records = [elem.text for elem in service_elem.findall("./txt-record")]
    required = {"k3s=1", "cluster=sugar", "env=dev", "role=server"}
    assert required.issubset(set(txt_records))

