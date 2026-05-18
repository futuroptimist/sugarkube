"""Regression tests for 2026-05-18 HA staging DHCP/IP outage hardening."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_node_ip_tls_san_is_opt_in_by_default():
    text = _script_text()
    assert 'SUGARKUBE_INCLUDE_NODE_IP_TLS_SAN="${SUGARKUBE_INCLUDE_NODE_IP_TLS_SAN:-0}"' in text
    assert "if should_include_node_ip_tls_san; then" in text
    assert 'install_args+=(--tls-san "${node_ip}")' in text


def test_node_ip_detection_is_gated_behind_tls_san_opt_in():
    text = _script_text()
    assert "Node-IP TLS SAN opt-in is enabled, but node IP detection failed; omitting IP SAN" in text
    assert text.count('if node_ip="$(detect_node_primary_ipv4)"; then') == text.count(
        "if should_include_node_ip_tls_san; then"
    )


def test_join_server_url_prefers_hostname_by_default():
    text = _script_text()
    assert 'SUGARKUBE_SERVER_URL_PREFER_IP="${SUGARKUBE_SERVER_URL_PREFER_IP:-0}"' in text
    assert "should_prefer_ip_server_url()" in text
    assert 'if [ -n "${ip_hint}" ] && should_prefer_ip_server_url; then' in text


def test_join_paths_refuse_unresolvable_hostname_urls():
    text = _script_text()
    assert "ensure_join_url_target_resolvable()" in text
    assert 'ensure_join_url_target_resolvable "${server_url_target}" "install_join"' in text
    assert 'ensure_join_url_target_resolvable "${server_url_target}" "install_agent"' in text
    assert "refusing to persist a systemd k3s URL" in text


def test_agent_join_url_uses_same_ip_opt_in_policy_as_server_join():
    text = _script_text()
    assert "event=install_agent server_url_type=ip" in text
    assert 'if [ -n "${ip_hint}" ] && should_prefer_ip_server_url; then' in text
    assert 'if [ -n "${ip_hint}" ] && is_ip_address_literal "${server_url_target}"; then' in text


def test_hostname_tls_sans_remain_present_for_server_installs():
    text = _script_text()
    assert '--tls-san "${MDNS_HOST}"' in text
    assert '--tls-san "${HN}"' in text
