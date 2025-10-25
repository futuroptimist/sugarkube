from pathlib import Path
import sys
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from k3s_mdns_parser import parse_avahi_browse_record
from mdns_helpers import build_publish_cmd, norm_host
from mdns_selfcheck import run_selfcheck


def test_build_publish_cmd_orders_args_correctly() -> None:
    cmd = build_publish_cmd(
        instance="k3s-sugar-dev@host0 (server)",
        service_type="_k3s-sugar-dev._tcp",
        port=6443,
        host="host0.local",
        txt={"phase": "server", "role": "leader"},
    )
    assert cmd[:4] == ["avahi-publish", "-s", "-H", "host0.local"]
    assert cmd[4:7] == ["k3s-sugar-dev@host0 (server)", "_k3s-sugar-dev._tcp", "6443"]
    assert "phase=server" in cmd
    assert "role=leader" in cmd


def test_norm_host_strips_trailing_dot_and_lowercases() -> None:
    assert norm_host("Sugarkube0.LOCAL.") == "sugarkube0.local"
    assert norm_host(None) == ""


def test_parse_avahi_browse_record_extracts_txt_fields() -> None:
    line = (
        "=;eth0;IPv4;k3s-sugar-dev@host0 (server);_k3s-sugar-dev._tcp;local;"
        "host0.local;192.0.2.10;6443;txt=phase=server;txt=role=server;txt=phase"
    )
    record = parse_avahi_browse_record(line)
    assert record is not None
    assert record["host"] == "host0.local"
    assert record["txt"]["phase"] == "server"
    assert record["txt"]["role"] == "server"
    assert record["txt"].get("phase") == "server"
    assert "phase" in record["txt"]


def test_run_selfcheck_falls_back_to_avahi_when_resolvectl_lacks_txt() -> None:
    logs: List[str] = []

    def logger(message: str) -> None:
        logs.append(message)

    instance = "k3s-sugar-dev@host0.local (server)"
    service_type = "_k3s-sugar-dev._tcp"
    expected_host = "host0.local"

    resolvectl_calls = []
    avahi_calls = []

    def fake_resolvectl(instance_arg: str, service_type_arg: str, *, domain: str = "local"):
        resolvectl_calls.append((instance_arg, service_type_arg, domain))
        return [
            {
                "instance": instance_arg,
                "type": service_type_arg,
                "domain": domain,
                "host": expected_host,
                "addresses": [],
                "addr": "",
                "txt": {},
                "source": "resolvectl",
            }
        ]

    def fake_avahi(service_type_arg: str, *, domain: str = "local"):
        avahi_calls.append((service_type_arg, domain))
        return [
            {
                "instance": instance,
                "type": service_type_arg,
                "domain": domain,
                "host": expected_host,
                "addresses": ["192.0.2.10"],
                "addr": "192.0.2.10",
                "txt": {"phase": "server", "role": "server"},
                "source": "avahi-browse",
            }
        ]

    record = run_selfcheck(
        instance=instance,
        service_type=service_type,
        domain="local",
        expected_host=expected_host,
        expected_ip=None,
        require_phase="server",
        require_role="server",
        require_ipv4=False,
        retries=1,
        delay=0.0,
        logger=logger,
        resolvectl=fake_resolvectl,
        avahi=fake_avahi,
        sleep=lambda _: None,
    )

    assert record is not None
    assert record["source"] == "avahi-browse"
    assert resolvectl_calls == [(instance, service_type, "local")]
    assert avahi_calls == [(service_type, "local")]
    assert any("resolvectl did not yield a matching record" in entry for entry in logs)


def test_run_selfcheck_logs_missing_phase_reason() -> None:
    logs: List[str] = []

    def logger(message: str) -> None:
        logs.append(message)

    instance = "k3s-sugar-dev@host0.local (server)"
    service_type = "_k3s-sugar-dev._tcp"

    def fake_resolvectl(instance_arg: str, service_type_arg: str, *, domain: str = "local"):
        return [
            {
                "instance": instance_arg,
                "type": service_type_arg,
                "domain": domain,
                "host": "host0.local",
                "addresses": ["192.0.2.10"],
                "addr": "192.0.2.10",
                "txt": {"role": "server"},
                "source": "resolvectl",
            }
        ]

    def fake_avahi(service_type_arg: str, *, domain: str = "local"):
        return []

    record = run_selfcheck(
        instance=instance,
        service_type=service_type,
        domain="local",
        expected_host="host0.local",
        expected_ip=None,
        require_phase="server",
        require_role=None,
        require_ipv4=False,
        retries=1,
        delay=0.0,
        logger=logger,
        resolvectl=fake_resolvectl,
        avahi=fake_avahi,
        sleep=lambda _: None,
    )

    assert record is None
    assert any("phase=<missing>" in entry for entry in logs)
