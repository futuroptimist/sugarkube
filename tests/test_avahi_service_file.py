import os
import shlex
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "k3s-discover.sh"


@pytest.fixture()
def avahi_env(tmp_path):
    services_dir = tmp_path / "avahi" / "services"
    services_dir.mkdir(parents=True)

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()

    sudo_stub = stub_dir / "sudo"
    sudo_stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            cmd="$1"
            shift || true
            case "${cmd}" in
              install)
                if [ "${1:-}" = "-d" ]; then
                  dir="${SUGARKUBE_TEST_AVAHI_DIR:?}"
                  mkdir -p "${dir}"
                  exit 0
                fi
                ;;
              rm)
                dir="${SUGARKUBE_TEST_AVAHI_DIR:?}"
                rm -f "${dir}/k3s-https.service" || true
                exit 0
                ;;
              systemctl)
                exit 0
                ;;
              tee)
                exec tee "$@"
                ;;
              *)
                exec "${cmd}" "$@"
                ;;
            esac
            """
        ),
        encoding="utf-8",
    )
    sudo_stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    env.setdefault("SUGARKUBE_CLUSTER", "sugar")
    env.setdefault("SUGARKUBE_ENV", "dev")
    env["SUGARKUBE_TEST_AVAHI_DIR"] = str(services_dir)
    return env, services_dir


def _call_publish_service(env: dict, service_file: Path, extra_records):
    records = " ".join(shlex.quote(record) for record in extra_records)
    command = (
        f"source {shlex.quote(str(SCRIPT))}"
        f" && AVAHI_SERVICE_FILE={shlex.quote(str(service_file))}"
        f" publish_avahi_service server 6443 {records}"
    )
    return subprocess.run(
        ["bash", "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_publish_service_writes_valid_xml(avahi_env):
    env, services_dir = avahi_env
    service_file = services_dir / "k3s-sugar-dev.service"

    result = _call_publish_service(env, service_file, ["leader=pi1.local", "state=ready"])

    assert result.returncode == 0
    assert service_file.exists()

    content = service_file.read_text(encoding="utf-8")
    assert "<!-- optional -->" in content

    sanitized = content.replace("<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">\n", "")
    root = ET.fromstring(sanitized)

    assert root.tag == "service-group"
    name = root.findtext("name")
    assert name == "k3s API sugar/dev on %h"

    service = root.find("service")
    assert service is not None
    assert service.findtext("type") == "_https._tcp"
    assert service.findtext("port") == "6443"

    records = [element.text for element in service.findall("txt-record")]
    assert records == [
        "k3s=1",
        "cluster=sugar",
        "env=dev",
        "role=server",
        "leader=pi1.local",
        "state=ready",
    ]
