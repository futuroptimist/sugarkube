"""Ensure node IP and flannel bindings survive interface changes."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "configure_k3s_node_ip.sh"
TLS_TEMPLATE = (
    REPO_ROOT / "systemd" / "etc" / "rancher" / "k3s" / "config.yaml.d" / "10-sugarkube-tls.yaml"
)


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_wlan_toggle_preserves_wired_node_ip(tmp_path: Path) -> None:
    """K3s keeps using the wired interface after WLAN comes back."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    wired_ip = "192.168.50.12"
    wlan_ip = "10.2.3.4"

    ip_stub = bin_dir / "ip"
    ip_script = textwrap.dedent(
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ge 5 ] && [ "$1" = "-4" ] && [ "$2" = "-o" ] && [ "$3" = "addr" ] \
  && [ "$4" = "show" ]; then
  case "$5" in
    eth0)
      echo "2: eth0    inet {wired_ip}/24 brd 192.168.50.255 scope global eth0"
      exit 0
      ;;
    wlan0)
      echo "3: wlan0    inet {wlan_ip}/24 brd 10.2.3.255 scope global wlan0"
      exit 0
      ;;
  esac
fi
echo "Unsupported invocation: $*" >&2
exit 1
"""
    )
    _write_exec(ip_stub, ip_script)

    systemctl_log = tmp_path / "systemctl.log"
    systemctl_stub = bin_dir / "systemctl"
    systemctl_script = textwrap.dedent(
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$@" >> '{systemctl_log}'
case "$1" in
  daemon-reload)
    exit 0
    ;;
  is-active)
    exit 0
    ;;
  restart)
    exit 0
    ;;
  list-unit-files)
    exit 0
    ;;
esac
exit 0
"""
    )
    _write_exec(systemctl_stub, systemctl_script)

    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    for unit_name in ("k3s.service", "k3s-agent.service"):
        (systemd_dir / unit_name).write_text("[Unit]\nDescription=stub\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "IFACE": "eth0",
            "IP_CMD": str(ip_stub),
            "SYSTEMCTL_BIN": str(systemctl_stub),
            "SYSTEMD_SYSTEM_DIR": str(systemd_dir),
            "UNIT_SEARCH_PATHS": str(systemd_dir),
            "LOG_DIR": str(tmp_path / "log"),
            "K3S_CONFIG_DIR": str(tmp_path / "etc" / "rancher" / "k3s"),
            "TLS_SAN_TEMPLATE_PATH": str(TLS_TEMPLATE),
            "SUGARKUBE_FLANNEL_IFACE": "eth0",
        }
    )

    subprocess.run(["bash", str(SCRIPT_PATH)], check=True, env=env, text=True)

    server_dropin = systemd_dir / "k3s.service.d" / "10-node-ip.conf"
    agent_dropin = systemd_dir / "k3s-agent.service.d" / "10-node-ip.conf"

    server_lines = server_dropin.read_text(encoding="utf-8").splitlines()
    agent_lines = agent_dropin.read_text(encoding="utf-8").splitlines()

    assert server_lines == [
        "[Service]",
        f"Environment=K3S_NODE_IP={wired_ip}",
        "Environment=K3S_FLANNEL_IFACE=eth0",
    ]
    assert agent_lines == [
        "[Service]",
        f"Environment=K3S_NODE_IP={wired_ip}",
    ]

    systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert systemctl_calls, "systemctl should have been invoked"
    assert any("daemon-reload" in line for line in systemctl_calls)
    assert any(line == "restart k3s.service" for line in systemctl_calls)
    assert any(line == "restart k3s-agent.service" for line in systemctl_calls)
