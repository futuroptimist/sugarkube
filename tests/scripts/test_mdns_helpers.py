import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from k3s_mdns_parser import parse_avahi_resolved_line  # noqa: E402
from mdns_helpers import build_publish_cmd, norm_host  # noqa: E402


def test_build_publish_cmd_orders_args_correctly():
    cmd = build_publish_cmd(
        instance="k3s-sugar-dev@pi.local (server)",
        service_type="_k3s-sugar-dev._tcp",
        port=6443,
        host="pi.local",
        txt={"phase": "server", "role": "server"},
    )

    assert cmd[:2] == ["avahi-publish", "-s"]
    assert cmd[2:4] == ["-H", "pi.local"]
    assert cmd[4:7] == [
        "k3s-sugar-dev@pi.local (server)",
        "_k3s-sugar-dev._tcp",
        "6443",
    ]
    assert "phase=server" in cmd
    assert "role=server" in cmd


def test_norm_host_strips_trailing_dot_and_lowercases():
    assert norm_host("Sugarkube0.LOCAL.") == "sugarkube0.local"
    assert norm_host(None) == ""


def test_parse_avahi_resolved_line_extracts_txt_fields():
    line = (
        "=;eth0;IPv4;k3s-sugar-dev@pi.local (server);_k3s-sugar-dev._tcp;local;"
        "pi.local;192.0.2.10;6443;txt=phase=server;txt=role=server;txt=state"
    )
    parsed = parse_avahi_resolved_line(line)
    assert parsed is not None
    assert parsed["instance"] == "k3s-sugar-dev@pi.local (server)"
    assert parsed["addr"] == "192.0.2.10"
    assert parsed["txt"]["phase"] == "server"
    assert parsed["txt"]["role"] == "server"
    assert parsed["txt"]["state"] == ""
