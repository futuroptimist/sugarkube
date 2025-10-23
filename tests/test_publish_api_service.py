import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


def test_render_api_service_generates_expected_xml(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    sudo = bin_dir / "sudo"
    sudo.write_text("#!/usr/bin/env bash\nset -euo pipefail\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(0o755)

    systemctl = bin_dir / "systemctl"
    systemctl.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    systemctl.chmod(0o755)

    service_dir = tmp_path / "avahi"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(service_dir),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "--render-avahi-service", "api"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    xml_text = result.stdout
    root = ET.fromstring(xml_text)

    name = root.find("name")
    assert name is not None
    assert name.text == "k3s API sugar/dev [server] on %h"

    txt_records = [elem.text for elem in root.findall(".//txt-record")]
    assert set(txt_records) == {
        "k3s=1",
        "cluster=sugar",
        "env=dev",
        "role=server",
    }
