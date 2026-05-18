"""Regression coverage for durable TLS SAN identity defaults."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "k3s-discover.sh"


def test_outage_regression_tls_san_raw_ip_not_default() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'TLS_SAN_INCLUDE_NODE_IP="${SUGARKUBE_TLS_SAN_INCLUDE_NODE_IP:-0}"' in text
    assert 'install_args+=(--tls-san "${node_ip}")' in text
    assert '[ "${TLS_SAN_INCLUDE_NODE_IP}" = "1" ]' in text


def test_outage_regression_join_prefers_hostname_server_url() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'local server_url_target="${server}"' in text
    assert 'SUGARKUBE_SERVER_URL_PREFER_IP:-0' in text
