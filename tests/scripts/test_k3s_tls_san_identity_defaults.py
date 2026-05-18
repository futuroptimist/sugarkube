from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_node_ip_tls_san_is_opt_in_by_default() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SUGARKUBE_INCLUDE_NODE_IP_TLS_SAN:-0" in text


def test_hostname_tls_sans_remain_default_identity() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '--tls-san "${MDNS_HOST}"' in text
    assert '--tls-san "${HN}"' in text


def test_install_paths_gate_ipv4_tls_san_with_opt_in_helper() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "should_include_node_ip_tls_san" in text
    assert text.count("if should_include_node_ip_tls_san;") >= 3
