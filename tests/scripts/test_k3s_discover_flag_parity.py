"""Validate flag parity enforcement in k3s-discover join flows."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"
PARITY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_server_flag_parity.sh"


def _write_stub(path: Path, *lines: str) -> None:
    path.write_text("".join(lines), encoding="utf-8")
    path.chmod(0o755)


def test_join_aborts_when_flag_parity_fails(tmp_path: Path) -> None:
    """A server join must stop when critical flags diverge."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    fixture = tmp_path / "mdns.txt"
    fixture.write_text(
        "\n".join(
            [
                (
                    "=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;"
                    "sugarkube0.local;192.168.1.10;6443;"
                ),
                (
                    "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
                    "txt=leader=sugarkube0.local;txt=phase=server"
                ),
            ]
        ),
        encoding="utf-8",
    )

    join_gate_log = tmp_path / "join-gate.log"
    curl_log = tmp_path / "curl.log"

    _write_stub(
        bin_dir / "check_apiready.sh",
        "#!/usr/bin/env bash\n",
        "set -euo pipefail\n",
        "exit 0\n",
    )
    _write_stub(
        bin_dir / "join_gate.sh",
        "#!/usr/bin/env bash\n",
        "set -euo pipefail\n",
        f"printf '%s\\n' \"$*\" >> '{join_gate_log}'\n",
        "exit 0\n",
    )
    _write_stub(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "iptables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ip6tables", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "apt-get", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n",
        "set -euo pipefail\n",
        f"echo curl >> '{curl_log}'\n",
        "exit 0\n",
    )
    _write_stub(bin_dir / "avahi-publish-service", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "avahi-publish", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "avahi-resolve", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "avahi-browse", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "ss", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "l4_probe.sh", "#!/usr/bin/env bash\nexit 0\n")
    _write_stub(bin_dir / "configure_avahi.sh", "#!/usr/bin/env bash\nexit 0\n")

    server_config = tmp_path / "server-config.yaml"
    server_config.write_text(
        "\n".join(
            [
                "cluster-cidr: 10.42.0.0/16",
                "service-cidr: 10.43.0.0/16",
                "cluster-domain: cluster.local",
                "flannel-backend: vxlan",
                "secrets-encryption: true",
            ]
        ),
        encoding="utf-8",
    )

    server_service = tmp_path / "k3s.service"
    server_service.write_text(
        "\n".join(
            [
                "[Service]",
                "ExecStart=/usr/local/bin/k3s server \\",
                "  --cluster-cidr=10.42.0.0/16 \\",
                "  --service-cidr=10.43.0.0/16",
            ]
        ),
        encoding="utf-8",
    )

    intended_config = tmp_path / "intended-config.yaml"
    intended_config.write_text(
        "\n".join(
            [
                "cluster-cidr: 10.42.0.0/16",
                "service-cidr: 10.43.0.0/16",
                "cluster-domain: dev.local",
                "flannel-backend: wireguard-native",
                "secrets-encryption: false",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_SERVERS": "3",
            "SUGARKUBE_TOKEN": "dummy",
            "DISCOVERY_ATTEMPTS": "1",
            "DISCOVERY_WAIT_SECS": "0",
            "SUGARKUBE_SKIP_MDNS_SELF_CHECK": "1",
            "SUGARKUBE_MDNS_FIXTURE_FILE": str(fixture),
            "SUGARKUBE_RUNTIME_DIR": str(tmp_path / "run"),
            "SUGARKUBE_AVAHI_SERVICE_DIR": str(tmp_path / "avahi"),
            "SUGARKUBE_API_READY_CHECK_BIN": str(bin_dir / "check_apiready.sh"),
            "SUGARKUBE_JOIN_GATE_BIN": str(bin_dir / "join_gate.sh"),
            "SUGARKUBE_MDNS_DBUS": "0",
            "SUGARKUBE_MDNS_WIRE_PROOF": "0",
            "SUGARKUBE_L4_PROBE_BIN": str(bin_dir / "l4_probe.sh"),
            "SUGARKUBE_CONFIGURE_AVAHI_BIN": str(bin_dir / "configure_avahi.sh"),
            "SUGARKUBE_SERVER_CONFIG_PATH": str(server_config),
            "SUGARKUBE_SERVER_SERVICE_PATH": str(server_service),
            "SUGARKUBE_INTENDED_K3S_CONFIG_PATH": str(intended_config),
            "SUGARKUBE_SERVER_FLAG_PARITY_BIN": str(PARITY_SCRIPT),
            "SUGARKUBE_SIMPLE_DISCOVERY": "0",  # Use legacy discovery for this test
            "SUGARKUBE_SKIP_ABSENCE_GATE": "0",  # Enable absence gate for legacy flow
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0, result.stderr
    assert "Flag parity check failed" in result.stderr
    assert "flannel-backend" in result.stderr
    assert "secrets-encryption" in result.stderr
    assert "cluster-domain" in result.stderr
    assert not curl_log.exists(), "Installer should not have been invoked"
    assert not join_gate_log.exists(), "Join gate should not be touched on parity failure"


def test_proxy_mode_falls_back_for_pre_133(tmp_path: Path) -> None:
    intended_config = tmp_path / "intended.yaml"
    intended_config.write_text(
        "\n".join(
            [
                "cluster-cidr: 10.42.0.0/16",
                "service-cidr: 10.43.0.0/16",
                "cluster-domain: cluster.local",
                "flannel-backend: vxlan",
                "secrets-encryption: false",
                "kube-proxy-arg:",
                "  - proxy-mode=nftables",
            ]
        ),
        encoding="utf-8",
    )

    server_config = tmp_path / "server.yaml"
    server_config.write_text(
        "\n".join(
            [
                "cluster-cidr: 10.42.0.0/16",
                "service-cidr: 10.43.0.0/16",
                "cluster-domain: cluster.local",
                "flannel-backend: vxlan",
                "secrets-encryption: false",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "SUGARKUBE_INTENDED_K3S_CONFIG_PATH": str(intended_config),
            "SUGARKUBE_SERVER_CONFIG_PATH": str(server_config),
            "SUGARKUBE_DETECTED_KUBERNETES_VERSION": "v1.32.5+k3s1",
        }
    )

    result = subprocess.run(
        ["bash", str(PARITY_SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "falling back to legacy iptables" in result.stderr.lower()
