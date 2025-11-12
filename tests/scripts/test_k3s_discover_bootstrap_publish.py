import os
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple

BootstrapPublishResult = Tuple[
    subprocess.CompletedProcess[str],
    ET.ElementTree,
    str,
    Path,
    Path,
    Path,
]

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh")


def _hostname_short() -> str:
    return subprocess.check_output(["hostname", "-s"], text=True).strip()


def _run_bootstrap_publish(tmp_path: Path, mdns_host: str) -> BootstrapPublishResult:
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

    expected_host = mdns_host.rstrip(".")
    expected_ipv4 = "192.0.2.10"
    hosts_path = tmp_path / "avahi-hosts"
    resolve_log = tmp_path / "avahi-resolve.log"
    browse_log = tmp_path / "avahi-browse.log"

    avahi_resolve_host_name = bin_dir / "avahi-resolve-host-name"
    avahi_resolve_host_name.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "CALL:$*" >> '{resolve_log}'
            if [ "$#" -lt 3 ]; then
              echo "invalid args: $*" >> '{resolve_log}'
              exit 2
            fi
            host="$1"
            shift
            if [ "$host" != "{expected_host}" ]; then
              echo "unexpected host: $host" >> '{resolve_log}'
              exit 3
            fi
            if [ "${{1:-}}" != "-4" ] || [ "${{2:-}}" != "--timeout=1" ]; then
              echo "unexpected args order: $host $*" >> '{resolve_log}'
              exit 4
            fi
            if grep -q '^{expected_ipv4} {expected_host}$' '{hosts_path}' 2>/dev/null; then
              echo "SUCCESS {expected_host} -> {expected_ipv4}" >> '{resolve_log}'
              printf '%s\\t%s\\n' '{expected_host}' '{expected_ipv4}'
              exit 0
            fi
            echo "FAIL {expected_host}" >> '{resolve_log}'
            exit 1
            """
        ),
        encoding="utf-8",
    )
    avahi_resolve_host_name.chmod(0o755)

    # Mock avahi-browse for service verification
    avahi_browse = bin_dir / "avahi-browse"
    avahi_browse.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "AVAHI-BROWSE:$*" >> '{browse_log}'
            # Return output that contains the expected host
            echo "=;eth0;IPv4;k3s-sugar-dev@{expected_host} (bootstrap);_k3s-sugar-dev._tcp;local;{expected_host};{expected_ipv4};6443;"
            exit 0
            """
        ),
        encoding="utf-8",
    )
    avahi_browse.chmod(0o755)

    # Mock avahi-resolve for host record self-check (with -n flag)
    avahi_resolve = bin_dir / "avahi-resolve"
    avahi_resolve.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            echo "AVAHI-RESOLVE:$*" >> '{resolve_log}'
            # Handle -n flag for name resolution
            if [[ "$*" == *"-n"* ]]; then
              echo "{expected_host}	{expected_ipv4}"
              exit 0
            fi
            exit 1
            """
        ),
        encoding="utf-8",
    )
    avahi_resolve.chmod(0o755)

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
            "SUGARKUBE_AVAHI_HOSTS_PATH": str(hosts_path),
            "SUGARKUBE_EXPECTED_IPV4": expected_ipv4,
            "LEADER": expected_host,
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
    return result, tree, log_contents, service_file, hosts_path, resolve_log


def _txt_records(tree: ET.ElementTree) -> List[str]:
    return [node.text for node in tree.findall(".//txt-record")]


def test_bootstrap_publish_writes_static_service(tmp_path):
    hostname = f"{_hostname_short()}.local"
    (
        result,
        tree,
        systemctl_log,
        service_file,
        hosts_path,
        resolve_log,
    ) = _run_bootstrap_publish(tmp_path, hostname)

    name = tree.findtext("./name")
    assert name == f"k3s-sugar-dev@{hostname} (bootstrap)"

    service_type = tree.findtext(".//type")
    assert service_type == "_k3s-sugar-dev._tcp"

    host_name = tree.findtext(".//host-name")
    assert host_name == hostname

    port = tree.findtext(".//port")
    assert port == "6443"

    txt_records = _txt_records(tree)
    assert txt_records[:6] == [
        "k3s=1",
        "cluster=sugar",
        "env=dev",
        "role=bootstrap",
        "phase=bootstrap",
        f"leader={hostname}",
    ]

    extras = txt_records[6:]
    if extras:
        assert extras[0] == f"host={hostname}"
    if len(extras) >= 2:
        assert extras[1].startswith("ip4=")
        assert len(extras[1]) > 4
    if len(extras) >= 3:
        assert extras[2].startswith("ip6=")
        assert len(extras[2]) > 4

    assert (
        "SYSTEMCTL:reload avahi-daemon" in systemctl_log
        or "SYSTEMCTL:restart avahi-daemon" in systemctl_log
    )
    assert result.returncode == 0

    service_text = service_file.read_text(encoding="utf-8")
    assert "<host-name>" in service_text

    hosts_content = hosts_path.read_text(encoding="utf-8")
    assert hosts_content.strip().endswith(f"192.0.2.10 {hostname}")

    resolve_log_contents = resolve_log.read_text(encoding="utf-8")
    assert "FAIL" in resolve_log_contents
    assert "SUCCESS" in resolve_log_contents
    assert "SUCCESS" in resolve_log_contents.splitlines()[-1]


def test_bootstrap_publish_sanitizes_trailing_dot_hostname(tmp_path):
    raw_host = f"{_hostname_short()}.local."
    result, tree, _, _, _, resolve_log = _run_bootstrap_publish(tmp_path, raw_host)

    name = tree.findtext("./name")
    expected_host = raw_host.rstrip(".")
    assert name == f"k3s-sugar-dev@{expected_host} (bootstrap)"

    host_name = tree.findtext(".//host-name")
    assert host_name == expected_host

    txt_records = _txt_records(tree)
    assert f"leader={expected_host}" in txt_records
    assert "phase=bootstrap" in txt_records
    assert result.returncode == 0

    resolve_log_contents = resolve_log.read_text(encoding="utf-8")
    assert "SUCCESS" in resolve_log_contents
