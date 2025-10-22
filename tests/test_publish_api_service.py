import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "k3s-discover.sh"


def _make_stub(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_render_api_service_writes_expected_xml(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _make_stub(fakebin / "sudo", "#!/usr/bin/env bash\nexec \"$@\"\n")
    _make_stub(fakebin / "systemctl", "#!/usr/bin/env bash\nexit 0\n")

    service_dir = tmp_path / "avahi"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fakebin}:{env.get('PATH', '')}",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(service_dir),
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "--render-api-service"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    service_file = service_dir / "k3s-sugar-dev.service"
    xml_text = service_file.read_text(encoding="utf-8")
    root = ET.fromstring(xml_text)
    txt_records = {elem.text for elem in root.findall(".//txt-record")}
    assert {"k3s=1", "cluster=sugar", "env=dev", "role=server"}.issubset(txt_records)

    name = root.find("name")
    assert name is not None
    assert name.text == "k3s API sugar/dev on %h"

    port = root.find(".//port")
    assert port is not None
    assert port.text == "6443"
