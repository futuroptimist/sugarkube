import sys
from pathlib import Path

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from k3s_mdns_parser import parse_mdns_records  # noqa: E402


def test_parse_bootstrap_and_server_ipv4_preferred():
    # Simulated avahi-browse --parsable --resolve lines (IPv4 and IPv6 for same host+role)
    lines = [
        (
            "=;eth0;IPv6;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local;"
            "host0.local;fe80::1;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            "txt=phase=bootstrap;txt=leader=host0.local"
        ),
        (
            "=;eth0;IPv4;k3s-sugar-dev@host0 (bootstrap);_k3s-sugar-dev._tcp;local;"
            "host0.local;192.168.1.10;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            "txt=phase=bootstrap;txt=leader=host0.local"
        ),
        (
            "=;eth0;IPv4;k3s-sugar-dev@host1 (server);_k3s-sugar-dev._tcp;local;"
            "host1.local;192.168.1.11;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;"
            "txt=leader=host1.local;txt=phase=server"
        ),
    ]
    recs = parse_mdns_records(lines, "sugar", "dev")
    # one bootstrap (host0) and one server (host1)
    roles = {r.txt.get("role") for r in recs}
    assert roles == {"bootstrap", "server"}
    # IPv4 should be preferred for host0/bootstrap
    boot = [r for r in recs if r.txt.get("role") == "bootstrap"][0]
    assert boot.address == "192.168.1.10"
    assert boot.port == 6443
    server = [r for r in recs if r.txt.get("role") == "server"][0]
    assert server.txt.get("phase") == "server"
    assert server.txt.get("leader") == "host1.local"


def test_parse_unresolved_bootstrap_uses_service_name():
    lines = [
        "+;eth0;IPv4;k3s-sugar-dev@host2 (bootstrap);_k3s-sugar-dev._tcp;local",
    ]
    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.host == "host2.local"
    assert record.txt.get("role") == "bootstrap"
    assert record.txt.get("leader") == "host2.local"
    assert record.port == 6443


def test_parse_trims_trailing_dots_from_host_fields():
    lines = [
        (
            "=;eth0;IPv4;k3s-sugar-dev@host6.local (bootstrap);_k3s-sugar-dev._tcp;"
            "local.;host6.local.;192.0.2.16;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            "txt=phase=bootstrap;txt=leader=host6.local."
        )
    ]

    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.host == "host6.local"
    assert record.txt.get("leader") == "host6.local"


def test_resolved_record_replaces_unresolved_placeholder():
    lines = [
        "+;eth0;IPv4;k3s-sugar-dev@host4 (bootstrap);_k3s-sugar-dev._tcp;local",
        (
            "=;eth0;IPv4;k3s-sugar-dev@host4 (bootstrap);_k3s-sugar-dev._tcp;local;"
            "host4.local;192.168.1.14;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
            "txt=role=bootstrap;txt=phase=bootstrap;txt=leader=leader0.local"
        ),
    ]

    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.address == "192.168.1.14"
    assert record.txt.get("leader") == "leader0.local"


def test_record_updates_when_txt_richer():
    lines = [
        (
            "=;eth0;IPv4;k3s-sugar-dev@host5 (server);_k3s-sugar-dev._tcp;local;"
            "host5.local;192.168.1.15;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server"
        ),
        (
            "=;eth0;IPv4;k3s-sugar-dev@host5 (server);_k3s-sugar-dev._tcp;local;"
            "host5.local;192.168.1.15;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=extra=1"
        ),
    ]

    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.txt.get("extra") == "1"


def test_parse_preserves_mixed_case_hostnames():
    lines = [
        (
            "=;eth0;IPv4;k3s-sugar-dev@HostMixed (bootstrap);_k3s-sugar-dev._tcp;local;"
            "HostMixed.local;192.168.1.21;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=bootstrap;"
            "txt=phase=bootstrap;txt=leader=HostMixed.local"
        )
    ]

    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.host == "HostMixed.local"
    assert record.txt.get("leader") == "HostMixed.local"


def test_parse_normalises_txt_whitespace_and_missing_host_falls_back_to_leader():
    lines = [
        (
            "=;eth0;IPv4;k3s-sugar-dev@LeaderHost (server);_k3s-sugar-dev._tcp;local;"
            ";192.168.1.30;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=ENV=dev;txt=role=SERVER ;"
            "txt=leader=LeaderHost.LOCAL.;txt=phase=Server "
        )
    ]

    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.host == "LeaderHost.local"
    assert record.txt.get("leader") == "LeaderHost.local"
    assert record.txt.get("phase") == "server"
    assert record.txt.get("role") == "server"


def test_parse_accepts_uppercase_cluster_and_env_values():
    lines = [
        (
            "=;eth0;IPv4;k3s-sugar-dev@host7 (server);_k3s-sugar-dev._tcp;local;"
            "host7.local;192.168.1.31;6443;"
            "txt=k3s=1;txt=cluster=SUGAR ;txt=ENV=DEV ;txt=role=server;txt=phase=server"
        )
    ]

    recs = parse_mdns_records(lines, "sugar", "dev")
    assert len(recs) == 1
    record = recs[0]
    assert record.txt.get("cluster") == "sugar"
    assert record.txt.get("env") == "dev"
    assert record.txt.get("role") == "server"
