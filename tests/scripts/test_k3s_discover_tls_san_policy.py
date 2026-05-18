"""Regression tests for 2026-05-18 HA staging DHCP/IP outage hardening."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_node_ip_tls_san_is_opt_in_by_default():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'SUGARKUBE_INCLUDE_NODE_IP_TLS_SAN="${SUGARKUBE_INCLUDE_NODE_IP_TLS_SAN:-0}"' in text
    assert 'if [ -n "${node_ip}" ] && should_include_node_ip_tls_san; then' in text


def test_join_server_url_prefers_hostname_by_default():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'SUGARKUBE_SERVER_URL_PREFER_IP="${SUGARKUBE_SERVER_URL_PREFER_IP:-0}"' in text
    assert 'if [ -n "${ip_hint}" ] && [ "${SUGARKUBE_SERVER_URL_PREFER_IP}" = "1" ]; then' in text


def test_hostname_tls_sans_remain_present_for_server_installs():
    text = SCRIPT.read_text(encoding="utf-8")
    assert '--tls-san "${MDNS_HOST}"' in text
    assert '--tls-san "${HN}"' in text
