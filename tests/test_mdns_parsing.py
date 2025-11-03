import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from k3s_mdns_parser import MdnsRecord, parse_mdns_records  # noqa: E402


@pytest.fixture()
def sample_lines():
    return [
        (
            "+;eth0;IPv4;k3s API sugar/dev [server] on sugarkube0;_https._tcp;local;"
            "sugarkube0.local;192.168.86.41;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server"
        ),
        (
            "+;eth0;IPv6;k3s API sugar/dev [server] on sugarkube0;_https._tcp;local;"
            "sugarkube0.local;fd00::1;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server"
        ),
    ]


def test_parse_mdns_prefers_ipv4(sample_lines):
    records = parse_mdns_records(sample_lines, "sugar", "dev")
    assert len(records) == 1
    record = records[0]
    assert isinstance(record, MdnsRecord)
    assert record.host == "sugarkube0.local"
    assert record.port == 6443
    assert record.protocol == "IPv4"
    assert record.txt["k3s"] == "1"
    assert record.txt["cluster"] == "sugar"
    assert record.txt["env"] == "dev"
    assert record.txt["role"] == "server"


def test_parse_mdns_accepts_ipv6_when_only_option():
    lines = [
        (
            "+;eth0;IPv6;k3s API sugar/dev [server] on sugarkube1;_https._tcp;local;"
            "sugarkube1.local;fd00::2;6443;"
            "txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server"
        )
    ]
    records = parse_mdns_records(lines, "sugar", "dev")
    assert len(records) == 1
    assert records[0].protocol == "IPv6"
