import os
import re
import subprocess
from pathlib import Path


def _write_stub(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_net_debug_sanitized_masks_sensitive_data(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    ip_stub = """#!/usr/bin/env bash
if [ "$1" = "-o" ] && [ "$2" = "link" ] && [ "$3" = "show" ] && [ "$4" = "up" ]; then
  cat <<'OUT'
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP mode DEFAULT group default qlen 1000 link/ether aa:bb:cc:dd:ee:ff brd ff:ff:ff:ff:ff:ff
3: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1400 state UP mode DEFAULT group default qlen 1000 link/ether 11:22:33:44:55:66 brd ff:ff:ff:ff:ff:ff
OUT
  exit 0
fi

if [ "$1" = "-4" ] && [ "$2" = "-o" ] && [ "$3" = "addr" ] && [ "$4" = "show" ] && [ "$5" = "scope" ] && [ "$6" = "global" ]; then
  cat <<'OUT'
2: eth0    inet 192.168.1.15/24 brd 192.168.1.255 scope global dynamic eth0
OUT
  exit 0
fi

if [ "$1" = "route" ] && [ "$2" = "show" ] && [ "$3" = "default" ]; then
  echo "default via 192.168.1.1 dev eth0"
  exit 0
fi

exit 1
"""
    _write_stub(bin_dir / "ip", ip_stub)

    systemctl_stub = """#!/usr/bin/env bash
if [ "$1" = "is-active" ]; then
  exit 0
fi
exit 1
"""
    _write_stub(bin_dir / "systemctl", systemctl_stub)

    journalctl_stub = """#!/usr/bin/env bash
cat <<'OUT'
Nov 01 router avahi-daemon[123]: Authorization: Bearer secret-token
Nov 01 router avahi-daemon[123]: Service for host router.local at 10.0.0.5 TXT data ignored
OUT
"""
    _write_stub(bin_dir / "journalctl", journalctl_stub)

    avahi_browse_stub = """#!/usr/bin/env bash
cat <<'OUT'
=;eth0;IPv4;Test Server;_k3s-sugar-dev._tcp;local;sugarkube1.local;192.168.1.20;txt=role=server
=;eth0;IPv4;Follower;_k3s-sugar-dev._tcp;local;otherhost.local;10.0.0.25;txt=role=follower
OUT
"""
    _write_stub(bin_dir / "avahi-browse", avahi_browse_stub)

    avahi_resolve_stub = """#!/usr/bin/env bash
echo "sugarkube0.local\t172.20.10.5"
"""
    _write_stub(bin_dir / "avahi-resolve", avahi_resolve_stub)

    ss_stub = """#!/usr/bin/env bash
cat <<'OUT'
LISTEN 0 128 0.0.0.0:6443 0.0.0.0:* users:(())
LISTEN 0 128 0.0.0.0:2379 0.0.0.0:* users:(())
OUT
"""
    _write_stub(bin_dir / "ss", ss_stub)

    resolvectl_stub = """#!/usr/bin/env bash
cat <<'OUT'
Global: 1.1.1.1 2606:4700::1111
Link 2 (eth0): 192.168.1.1
OUT
"""
    _write_stub(bin_dir / "resolvectl", resolvectl_stub)

    nft_stub = """#!/usr/bin/env bash
if [ "$1" = "-j" ] && [ "$2" = "list" ] && [ "$3" = "ruleset" ]; then
  cat <<'OUT'
{"nftables": [{"chain": {"name": "kube-proxy", "hook": "prerouting", "policy": "accept", "counter": {"packets": 4, "bytes": 512}, "rules": [{"match": "ip daddr 10.23.45.67"}]}}]}
OUT
  exit 0
fi
exit 1
"""
    _write_stub(bin_dir / "nft", nft_stub)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["LOG_SALT"] = "0123456789abcdef"
    script_path = Path("scripts/net_debug_sanitized.sh").resolve()

    result = subprocess.run(
        ["bash", "-euo", "pipefail", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    output = result.stdout
    assert "secret-token" not in output
    assert "[REDACTED]" in output
    assert "otherhost.local" not in output
    assert "host-" in output
    assert "MAC-" in output
    assert "PUBLIC-" in output or "172." in output

    ips = re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", output)
    assert set(ips).issubset({"0.0.0.0", "127.0.0.1"})

    assert "mdns.services._k3s-sugar-dev._tcp.count: 2" in output
    assert "mdns.sugarkube0.resolve: yes" in output
    assert "kube.api.6443.listen: yes" in output
    assert "etcd.2379.listen: yes" in output
    assert "dataplane: nftables" in output
