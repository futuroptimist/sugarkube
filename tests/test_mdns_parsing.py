import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "mdns_parser.py"

_spec = importlib.util.spec_from_file_location("mdns_parser", MODULE_PATH)
mdns_parser = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
sys.modules[_spec.name] = mdns_parser
_spec.loader.exec_module(mdns_parser)  # type: ignore[misc]


def test_parser_prefers_ipv4_and_returns_txt_records():
    lines = [
        "+;eth0;IPv4;k3s API sugar/dev on sugarkube0;_https._tcp;local;sugarkube0.local;192.168.86.41;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server",
        "+;eth0;IPv6;k3s API sugar/dev on sugarkube0;_https._tcp;local;sugarkube0.local;fd00::1;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server",
    ]

    records = mdns_parser.parse_records(lines, "sugar", "dev")
    servers = [record for record in records if record.role == "server"]

    assert len(servers) == 1
    record = servers[0]
    assert record.host == "sugarkube0.local"
    assert record.port == "6443"
    assert record.protocol == "IPv4"
    assert record.txt["k3s"] == "1"
    assert record.txt["cluster"] == "sugar"
    assert record.txt["env"] == "dev"
    assert record.txt["role"] == "server"
