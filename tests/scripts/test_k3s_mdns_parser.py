import sys
from pathlib import Path

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from k3s_mdns_parser import parse_mdns_records  # noqa: E402


def test_parse_bootstrap_and_server_ipv4_preferred():
    # Simulated avahi-browse --parsable --resolve lines (IPv4 and IPv6 for same host+role)
    lines = [
        "=;eth0;IPv6;k3s API sugar/dev on host0;_https._tcp;local;host0.local;fe80::1;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;txt=leader=host0.local",
        "=;eth0;IPv4;k3s API sugar/dev on host0;_https._tcp;local;host0.local;192.168.1.10;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;txt=leader=host0.local",
        "=;eth0;IPv4;k3s API sugar/dev on host1;_https._tcp;local;host1.local;192.168.1.11;6443;"
        "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server",
    ]
    recs = parse_mdns_records(lines, "sugar", "dev")
    # one bootstrap (host0) and one server (host1)
    roles = {r.txt.get("role") for r in recs}
    assert roles == {"bootstrap", "server"}
    # IPv4 should be preferred for host0/bootstrap
    boot = [r for r in recs if r.txt.get("role") == "bootstrap"][0]
    assert boot.address == "192.168.1.10"
    assert boot.port == 6443
