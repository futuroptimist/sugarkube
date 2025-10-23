import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _render(role, *txt):
    env = {
        "SUGARKUBE_CLUSTER": "sugar",
        "SUGARKUBE_ENV": "dev",
    }
    cmd = ["bash", SCRIPT, "--render-avahi-service", role, "6443", *txt]
    out = subprocess.check_output(cmd, env=env, text=True)
    return ET.fromstring(out)  # must be valid XML


def test_render_bootstrap_xml_has_required_txt_records():
    root = _render("bootstrap", "leader=host0.local", "phase=bootstrap", "state=pending")
    name = root.find("./name")
    assert name is not None and "sugar/dev" in name.text

    svc = root.find("./service")
    assert svc is not None
    assert svc.findtext("./type") == "_https._tcp"
    assert svc.findtext("./port") == "6443"

    txts = [e.text for e in svc.findall("./txt-record")]
    # Must include required baseline and our extras
    for expected in [
        "k3s=1",
        "cluster=sugar",
        "env=dev",
        "role=bootstrap",
        "leader=host0.local",
        "phase=bootstrap",
        "state=pending",
    ]:
        assert expected in txts


def test_render_server_xml_has_role_server():
    root = _render("api")  # alias prints role=server XML
    svc = root.find("./service")
    txts = [e.text for e in svc.findall("./txt-record")]
    assert "role=server" in txts
