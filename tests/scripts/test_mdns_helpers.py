import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import mdns_selfcheck  # noqa: E402
from k3s_mdns_parser import parse_mdns_records  # noqa: E402
from mdns_helpers import _same_host, build_publish_cmd, norm_host  # noqa: E402


def test_build_publish_cmd_orders_args_correctly():
    cmd = build_publish_cmd(
        instance="X",
        service_type="_http._tcp",
        port=6443,
        host="h.local",
        txt={"phase": "bootstrap", "role": "candidate"},
    )
    assert cmd[:3] == ["avahi-publish", "-s", "-H"]
    assert cmd[3] == "h.local"
    assert cmd[4:7] == ["X", "_http._tcp", "6443"]
    assert "phase=bootstrap" in cmd and "role=candidate" in cmd


def test_norm_host_strips_trailing_dot_and_lowercases():
    assert norm_host("Sugarkube0.LOCAL.") == "sugarkube0.local"


def test_same_host_handles_control_characters():
    assert _same_host("host0.local\x00", "HOST0.LOCAL")


def test_parse_mdns_records_extracts_phase_and_role_from_txt():
    line = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;"
        "host0.local.;192.0.2.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
        "txt=phase=server;txt=role"
    )
    records = parse_mdns_records([line], "sugar", "dev")
    assert len(records) == 1
    record = records[0]
    assert record.txt["phase"] == "server"
    assert record.txt["role"] == "server"


def test_gather_records_falls_back_when_resolvectl_lacks_txt(monkeypatch):
    calls = []

    def fake_resolve(*args, **kwargs):
        calls.append("resolvectl")
        return [
            {
                "instance": "k3s-sugar-dev@node.local (server)",
                "type": "_k3s-sugar-dev._tcp",
                "domain": "local",
                "host": "node.local",
                "addr": "",
                "port": 6443,
                "txt": {},
                "addresses": [],
            }
        ]

    def fake_avahi(*args, **kwargs):
        calls.append("avahi")
        return [
            {
                "instance": "k3s-sugar-dev@node.local (server)",
                "type": "_k3s-sugar-dev._tcp",
                "domain": "local",
                "host": "node.local",
                "addr": "192.0.2.10",
                "port": 6443,
                "txt": {"phase": "server", "role": "server"},
                "addresses": ["192.0.2.10"],
            }
        ]

    monkeypatch.setattr(mdns_selfcheck, "resolve_with_resolvectl", fake_resolve)
    monkeypatch.setattr(mdns_selfcheck, "resolve_with_avahi_browse", fake_avahi)

    stream = io.StringIO()
    logger = mdns_selfcheck.TimestampedLogger(stderr=stream)

    records = mdns_selfcheck.gather_records(
        instance="k3s-sugar-dev@node.local (server)",
        service_type="_k3s-sugar-dev._tcp",
        domain="local",
        resolvectl_runner=None,
        avahi_runner=None,
        logger=logger,
    )

    assert ["resolvectl", "avahi"] == calls
    assert records and records[0]["txt"]["phase"] == "server"
    assert "falling back to avahi-browse" in stream.getvalue()


def test_select_record_logs_missing_phase():
    record = {
        "instance": "k3s-sugar-dev@node.local (server)",
        "type": "_k3s-sugar-dev._tcp",
        "domain": "local",
        "host": "node.local",
        "addr": "192.0.2.10",
        "port": 6443,
        "txt": {"role": "server"},
        "addresses": ["192.0.2.10"],
    }
    stream = io.StringIO()
    logger = mdns_selfcheck.TimestampedLogger(stderr=stream)

    match = mdns_selfcheck.select_record(
        [record],
        expected_host="node.local",
        required_phase="server",
        required_role=None,
        expected_addr="",
        require_ipv4=False,
        logger=logger,
        attempt=1,
        retries=1,
    )

    assert match is None
    output = stream.getvalue()
    assert "phase/role mismatch" in output
    assert "phase=<missing>" in output
