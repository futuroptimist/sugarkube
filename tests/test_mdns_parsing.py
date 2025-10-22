from scripts.mdns_parser import parse_avahi_output


def test_parser_prefers_ipv4_and_extracts_txt():
    sample = (
        "+;eth0;IPv4;k3s API sugar/dev on sugarkube0;_https._tcp;local;"
        "sugarkube0.local;192.168.86.41;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
        "+;eth0;IPv6;k3s API sugar/dev on sugarkube0;_https._tcp;local;"
        "sugarkube0.local;fd00::1;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
    )

    records, resolved = parse_avahi_output(sample, "sugar", "dev")
    assert resolved == [line for line in sample.splitlines() if line]
    assert len(records) == 1, f"expected a single IPv4-preferred record, got {records!r}"

    record = records[0]
    assert record.hostname == "sugarkube0.local"
    assert record.address == "192.168.86.41"
    assert record.port == 6443
    assert record.txt["k3s"] == "1"
    assert record.txt["cluster"] == "sugar"
    assert record.txt["env"] == "dev"
    assert record.txt["role"] == "server"
