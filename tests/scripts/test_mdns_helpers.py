from unittest import mock

import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from mdns_helpers import build_publish_cmd, norm_host
from k3s_mdns_parser import parse_mdns_records
from mdns_selfcheck import gather_records, run_selfcheck


def test_build_publish_cmd_orders_args_correctly():
    cmd = build_publish_cmd(
        instance="service@example (server)",
        service_type="_k3s-sugar-dev._tcp",
        port=6443,
        host="Host.LOCAL.",
        txt={"phase": "bootstrap", "role": "candidate"},
    )
    assert cmd[:3] == ["avahi-publish", "-s", "-H"]
    assert cmd[3] == "Host.LOCAL."
    assert cmd[4:7] == ["service@example (server)", "_k3s-sugar-dev._tcp", "6443"]
    assert "phase=bootstrap" in cmd
    assert "role=candidate" in cmd


def test_norm_host_strips_trailing_dot_and_lowercases():
    assert norm_host("Sugarkube0.LOCAL.") == "sugarkube0.local"
    assert norm_host(None) == ""


def test_parse_mdns_records_parses_txt_tokens():
    line = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;"
        "local;host0.local;192.0.2.10;6443;"
        "txt=cluster=sugar;txt=env=dev;txt=phase=server;txt=role=server;txt=flag"
    )
    records = parse_mdns_records([line], "sugar", "dev")
    assert len(records) == 1
    record = records[0]
    assert record.txt["phase"] == "server"
    assert record.txt["role"] == "server"
    assert record.txt["flag"] == ""


def test_gather_records_prefers_resolvectl_then_falls_back(monkeypatch):
    instance = "k3s-sugar-dev@host0 (server)"
    service_type = "_k3s-sugar-dev._tcp"
    resolvectl_records = [
        {
            "instance": instance,
            "type": service_type,
            "domain": "local",
            "host": "host0.local",
            "addrs": ["192.0.2.10"],
            "addr": "192.0.2.10",
            "txt": {},
            "source": "resolvectl",
        }
    ]
    avahi_records = [
        {
            "instance": instance,
            "type": service_type,
            "domain": "local",
            "host": "host0.local",
            "addrs": ["192.0.2.10"],
            "addr": "192.0.2.10",
            "txt": {"phase": "server"},
            "source": "avahi-browse",
        }
    ]

    fake_resolve = mock.Mock(return_value=resolvectl_records)
    fake_browse = mock.Mock(return_value=avahi_records)
    monkeypatch.setattr(
        "mdns_selfcheck.resolve_with_resolvectl", fake_resolve
    )
    monkeypatch.setattr(
        "mdns_selfcheck.resolve_with_avahi_browse", fake_browse
    )

    records, used_fallback = gather_records(instance, service_type)

    assert used_fallback is True
    assert records == avahi_records
    fake_resolve.assert_called_once()
    fake_browse.assert_called_once()


def test_run_selfcheck_logs_missing_phase(monkeypatch, capsys):
    instance = "k3s-sugar-dev@host0 (server)"
    service_type = "_k3s-sugar-dev._tcp"
    record = {
        "instance": instance,
        "type": service_type,
        "domain": "local",
        "host": "host0.local",
        "addrs": ["192.0.2.10"],
        "addr": "192.0.2.10",
        "txt": {},
        "source": "resolvectl",
    }

    monkeypatch.setattr(
        "mdns_selfcheck.gather_records",
        mock.Mock(return_value=([record], False)),
    )

    success, observed = run_selfcheck(
        instance=instance,
        service_type=service_type,
        domain="local",
        expected_host="host0.local",
        require_phase="server",
        retries=1,
        delay_ms=0,
        sleep=lambda _: None,
    )

    assert success is False
    assert observed is None
    stderr = capsys.readouterr().err
    assert "missing TXT key 'phase'" in stderr
