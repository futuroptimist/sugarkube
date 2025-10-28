import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def _run_bootstrap_publish(tmp_path: Path, mdns_host: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    systemctl_log = tmp_path / "systemctl.log"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"SYSTEMCTL:$*\" >> '{systemctl_log}'\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_TOKEN": "dummy",
            "SUGARKUBE_MDNS_BOOT_RETRIES": "1",
            "SUGARKUBE_MDNS_BOOT_DELAY": "0",
            "SUGARKUBE_SKIP_SYSTEMCTL": "0",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_MDNS_HOST": mdns_host,
        }
    )

    result = subprocess.run(
        ["bash", SCRIPT, "--test-bootstrap-publish"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    service_file = tmp_path / "avahi" / "k3s-sugar-dev.service"
    tree = ET.parse(service_file)
    log_contents = systemctl_log.read_text(encoding="utf-8")
    return result, tree, log_contents


def _txt_records(tree: ET.ElementTree) -> List[str]:
    return [node.text for node in tree.findall(".//txt-record")]


def test_bootstrap_publish_writes_static_service(tmp_path):
    hostname = f"{_hostname_short()}.local"
    result, tree, systemctl_log = _run_bootstrap_publish(tmp_path, hostname)

    name = tree.findtext("./name")
    assert name == f"k3s-sugar-dev@{hostname} (bootstrap)"

    service_type = tree.findtext(".//type")
    assert service_type == "_k3s-sugar-dev._tcp"

    port = tree.findtext(".//port")
    assert port == "6443"

    txt_records = _txt_records(tree)
    assert txt_records == [
        "k3s=1",
        "cluster=sugar",
        "env=dev",
        "role=bootstrap",
        "phase=bootstrap",
        f"leader={hostname}",
    ]

    assert "SYSTEMCTL:reload avahi-daemon" in systemctl_log or "SYSTEMCTL:restart avahi-daemon" in systemctl_log
    assert result.returncode == 0


def test_bootstrap_publish_sanitizes_trailing_dot_hostname(tmp_path):
    raw_host = f"{_hostname_short()}.local."
    result, tree, _ = _run_bootstrap_publish(tmp_path, raw_host)

    name = tree.findtext("./name")
    expected_host = raw_host.rstrip(".")
    assert name == f"k3s-sugar-dev@{expected_host} (bootstrap)"

    txt_records = _txt_records(tree)
    assert txt_records[-1] == f"leader={expected_host}"
    assert "phase=bootstrap" in txt_records
    assert result.returncode == 0
