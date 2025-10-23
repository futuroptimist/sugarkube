import subprocess
import sys
from pathlib import Path

# Add scripts/ to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from k3s_mdns_query import query_mdns  # noqa: E402


def _sample_server_stdout() -> str:
    return (
        "=;eth0;IPv4;k3s API sugar/dev on host0;_https._tcp;local;host0.local;"
        "192.168.1.10;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;txt=role=server\n"
    )


def test_query_mdns_keeps_output_when_avahi_errors():
    messages = []

    def runner(command, capture_output, text, check):
        assert command[0] == "avahi-browse"
        assert capture_output and text and not check
        return subprocess.CompletedProcess(
            command,
            returncode=255,
            stdout=_sample_server_stdout(),
            stderr="Failed to resolve",
        )

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == ["host0.local"]
    assert any("255" in msg for msg in messages)


def test_query_mdns_bootstrap_leaders_uses_txt_leader(tmp_path):
    fixture = tmp_path / "mdns.txt"
    fixture.write_text(
        (
            "=;eth0;IPv4;k3s API sugar/dev on host1;_https._tcp;local;host1.local;"
            "192.168.1.11;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
            "txt=role=bootstrap;txt=leader=leader0.local\n"
            "=;eth0;IPv4;k3s API sugar/dev on host2;_https._tcp;local;host2.local;"
            "192.168.1.12;6443;txt=k3s=1;txt=cluster=sugar;txt=env=dev;"
            "txt=role=bootstrap\n"
        ),
        encoding="utf-8",
    )

    results = query_mdns(
        "bootstrap-leaders",
        "sugar",
        "dev",
        fixture_path=str(fixture),
    )

    assert results == ["leader0.local", "host2.local"]


def test_query_mdns_handles_missing_avahi():
    messages = []

    def runner(command, capture_output, text, check):
        raise FileNotFoundError("avahi-browse missing")

    results = query_mdns(
        "server-first",
        "sugar",
        "dev",
        runner=runner,
        debug=messages.append,
    )

    assert results == []
    assert any("not found" in message for message in messages)
