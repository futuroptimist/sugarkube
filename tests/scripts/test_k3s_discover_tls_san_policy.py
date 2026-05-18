"""Regression tests for 2026-05-18 HA staging DHCP/IP outage hardening."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"
NODE_IP = "192.168.50.12"
SERVER_HOST = "sugarkube0.local"
SHORT_HOST = "sugarkube1"
MDNS_HOST = f"{SHORT_HOST}.local"


def _write_stub(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _render_install(tmp_path: Path, mode: str, **env_overrides: str) -> tuple[list[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_stub(bin_dir / "hostname", f"#!/usr/bin/env bash\nprintf '%s\n' '{SHORT_HOST}'\n")

    ip_stub = bin_dir / "ip"
    _write_stub(
        ip_stub,
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        if [ "$#" -ge 5 ] && [ "$1" = "-4" ] && [ "$2" = "-o" ] \
          && [ "$3" = "addr" ] && [ "$4" = "show" ] && [ "$5" = "eth0" ]; then
          echo "2: eth0 inet {NODE_IP}/24 brd 192.168.50.255 scope global eth0"
          exit 0
        fi
        echo "Unsupported ip invocation: $*" >&2
        exit 1
        """,
    )

    _write_stub(
        bin_dir / "getent",
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        if [ "${{SUGARKUBE_TEST_GETENT_MODE:-resolve}}" = "fail" ]; then
          exit 2
        fi
        if [ "$#" -ge 2 ] && [ "$2" = "{SERVER_HOST}" ]; then
          case "$1" in
            hosts)
              echo "{NODE_IP} {SERVER_HOST}"
              exit 0
              ;;
            ahostsv4)
              echo "{NODE_IP} STREAM {SERVER_HOST}"
              exit 0
              ;;
          esac
        fi
        exit 2
        """,
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_HOSTNAME": SHORT_HOST,
            "SUGARKUBE_MDNS_HOST": MDNS_HOST,
            "SUGARKUBE_MDNS_INTERFACE": "eth0",
            "IP_CMD": str(ip_stub),
            "SUGARKUBE_TOKEN": "test-token",
            "SUGARKUBE_TEST_DISCOVERED_SERVER": SERVER_HOST,
            "SUGARKUBE_TEST_MDNS_SELECTED_HOST": SERVER_HOST,
            "SUGARKUBE_TEST_MDNS_SELECTED_IP": NODE_IP,
            "MDNS_SELECTED_PORT": "6443",
        }
    )
    env.update(env_overrides)

    result = subprocess.run(
        ["bash", str(SCRIPT), "--test-render-k3s-install", mode],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    env_lines = [
        line.split("\t", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("ENV\t")
    ]
    arg_lines = [
        line.split("\t", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("ARG\t")
    ]
    return env_lines, arg_lines


def _tls_san_values(args: list[str]) -> list[str]:
    return [value for flag, value in zip(args, args[1:]) if flag == "--tls-san"]


def test_single_server_rendered_args_use_hostname_sans_by_default(tmp_path: Path) -> None:
    _, args = _render_install(tmp_path, "single")

    assert args[0] == "server"
    assert _tls_san_values(args) == [MDNS_HOST, SHORT_HOST]
    assert NODE_IP not in _tls_san_values(args)


def test_cluster_init_rendered_args_use_hostname_sans_by_default(tmp_path: Path) -> None:
    _, args = _render_install(tmp_path, "cluster-init")

    assert args[:2] == ["server", "--cluster-init"]
    assert _tls_san_values(args) == [MDNS_HOST, SHORT_HOST]
    assert NODE_IP not in _tls_san_values(args)


def test_join_rendered_args_use_hostname_sans_and_hostname_url_by_default(tmp_path: Path) -> None:
    env_lines, args = _render_install(tmp_path, "join")

    assert f"K3S_URL=https://{SERVER_HOST}:6443" in env_lines
    assert f"SERVER_IP={NODE_IP}" in env_lines
    assert args[:3] == ["server", "--server", f"https://{SERVER_HOST}:6443"]
    assert _tls_san_values(args) == [SERVER_HOST, MDNS_HOST, SHORT_HOST]
    assert NODE_IP not in _tls_san_values(args)


def test_node_ip_tls_san_opt_in_adds_detected_raw_ipv4(tmp_path: Path) -> None:
    _, args = _render_install(tmp_path, "single", SUGARKUBE_INCLUDE_NODE_IP_TLS_SAN="1")

    assert _tls_san_values(args) == [MDNS_HOST, SHORT_HOST, NODE_IP]


def test_join_ip_preference_opt_in_uses_ip_hint_for_k3s_url(tmp_path: Path) -> None:
    env_lines, args = _render_install(tmp_path, "join", SUGARKUBE_SERVER_URL_PREFER_IP="1")

    assert f"K3S_URL=https://{NODE_IP}:6443" in env_lines
    assert f"SERVER_IP={NODE_IP}" in env_lines
    assert args[:3] == ["server", "--server", f"https://{NODE_IP}:6443"]
    assert _tls_san_values(args) == [SERVER_HOST, MDNS_HOST, SHORT_HOST]


def test_join_falls_back_to_ip_hint_when_hostname_is_not_durable_resolvable(
    tmp_path: Path,
) -> None:
    env_lines, args = _render_install(tmp_path, "join", SUGARKUBE_TEST_GETENT_MODE="fail")

    assert f"K3S_URL=https://{NODE_IP}:6443" in env_lines
    assert f"SERVER_IP={NODE_IP}" in env_lines
    assert args[:3] == ["server", "--server", f"https://{NODE_IP}:6443"]
    assert _tls_san_values(args) == [SERVER_HOST, MDNS_HOST, SHORT_HOST]


def test_agent_join_uses_hostname_url_by_default_and_ip_hint_only_when_opted_in(
    tmp_path: Path,
) -> None:
    default_env, default_args = _render_install(tmp_path, "agent")
    ip_env, ip_args = _render_install(tmp_path, "agent", SUGARKUBE_SERVER_URL_PREFER_IP="1")

    assert default_args[0] == "agent"
    assert f"K3S_URL=https://{SERVER_HOST}:6443" in default_env
    assert f"SERVER_IP={NODE_IP}" in default_env
    assert ip_args[0] == "agent"
    assert f"K3S_URL=https://{NODE_IP}:6443" in ip_env
    assert f"SERVER_IP={NODE_IP}" in ip_env


def test_agent_join_falls_back_to_ip_hint_when_hostname_is_not_durable_resolvable(
    tmp_path: Path,
) -> None:
    env_lines, args = _render_install(tmp_path, "agent", SUGARKUBE_TEST_GETENT_MODE="fail")

    assert args[0] == "agent"
    assert f"K3S_URL=https://{NODE_IP}:6443" in env_lines
    assert f"SERVER_IP={NODE_IP}" in env_lines


def _run_join_url_guard(
    tmp_path: Path,
    target: str,
    ip_hint: str | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_stub(
        bin_dir / "getent",
        """
        #!/usr/bin/env bash
        exit 2
        """,
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_HOSTNAME": SHORT_HOST,
            "SUGARKUBE_MDNS_HOST": MDNS_HOST,
        }
    )
    command = ["bash", str(SCRIPT), "--test-ensure-join-url-target", target]
    if ip_hint is not None:
        command.append(ip_hint)
    return subprocess.run(command, capture_output=True, text=True, env=env, check=False)


def test_hostname_join_url_guard_allows_validated_txt_ip_hint_when_nss_fails(
    tmp_path: Path,
) -> None:
    result = _run_join_url_guard(tmp_path, SERVER_HOST, NODE_IP)

    assert result.returncode == 0, result.stderr
    assert "reachable IP hint" in result.stderr
    assert f"server_url={SERVER_HOST}" in result.stderr
    assert f"ip_hint={NODE_IP}" in result.stderr


def test_hostname_join_url_guard_still_fails_without_nss_or_ip_hint(tmp_path: Path) -> None:
    result = _run_join_url_guard(tmp_path, SERVER_HOST)

    assert result.returncode == 1
    assert "no discovery IP hint is available" in result.stderr
    assert f"server_url={SERVER_HOST}" in result.stderr


def _run_remote_tls_san_check(
    tmp_path: Path,
    target: str,
    san_output: str,
    *,
    curl_exit: int = 0,
    openssl_s_client_exit: int = 0,
    openssl_x509_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_stub(
        bin_dir / "curl",
        """
        #!/usr/bin/env bash
        exit_code="${SUGARKUBE_TEST_CURL_EXIT:-0}"
        if [ "${exit_code}" != "0" ]; then
          exit "${exit_code}"
        fi
        printf '%s\n' 'fake-ca'
        """,
    )
    _write_stub(
        bin_dir / "openssl",
        """
        #!/usr/bin/env bash
        set -euo pipefail
        case "${1:-}" in
          s_client)
            exit_code="${SUGARKUBE_TEST_OPENSSL_S_CLIENT_EXIT:-0}"
            if [ "${exit_code}" != "0" ]; then
              exit "${exit_code}"
            fi
            printf '%s\n' 'fake-certificate'
            ;;
          x509)
            exit_code="${SUGARKUBE_TEST_OPENSSL_X509_EXIT:-0}"
            if [ "${exit_code}" != "0" ]; then
              exit "${exit_code}"
            fi
            printf '%s\n' "${SUGARKUBE_TEST_SAN_OUTPUT}"
            ;;
          *)
            echo "Unsupported openssl invocation: $*" >&2
            exit 2
            ;;
        esac
        """,
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "ALLOW_NON_ROOT": "1",
            "SUGARKUBE_CLUSTER": "sugar",
            "SUGARKUBE_ENV": "dev",
            "SUGARKUBE_HOSTNAME": SHORT_HOST,
            "SUGARKUBE_MDNS_HOST": MDNS_HOST,
            "SUGARKUBE_TEST_SAN_OUTPUT": san_output,
            "SUGARKUBE_TEST_CURL_EXIT": str(curl_exit),
            "SUGARKUBE_TEST_OPENSSL_S_CLIENT_EXIT": str(openssl_s_client_exit),
            "SUGARKUBE_TEST_OPENSSL_X509_EXIT": str(openssl_x509_exit),
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT), "--test-check-remote-tls-san", target],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_ip_join_url_tls_guard_rejects_hostname_only_remote_certificate(
    tmp_path: Path,
) -> None:
    san_output = f"X509v3 Subject Alternative Name:\n    DNS:{SERVER_HOST}, DNS:sugarkube0"

    result = _run_remote_tls_san_check(tmp_path, NODE_IP, san_output)

    assert result.returncode == 1
    assert "Server certificate SANs miss join host" in result.stderr
    assert f"server={NODE_IP}" in result.stderr


def test_ip_join_url_tls_guard_accepts_matching_remote_ip_san(tmp_path: Path) -> None:
    san_output = (
        "X509v3 Subject Alternative Name:\n"
        f"    DNS:{SERVER_HOST}, DNS:sugarkube0, IP Address:{NODE_IP}"
    )

    result = _run_remote_tls_san_check(tmp_path, NODE_IP, san_output)

    assert result.returncode == 0, result.stderr


def test_strict_ip_join_url_tls_guard_fails_closed_when_ca_fetch_fails(
    tmp_path: Path,
) -> None:
    result = _run_remote_tls_san_check(tmp_path, NODE_IP, "", curl_exit=7)

    assert result.returncode == 1
    assert "Failed to download server CA bundle" in result.stderr
    assert f"server={NODE_IP}" in result.stderr


def test_strict_ip_join_url_tls_guard_fails_closed_when_certificate_inspection_fails(
    tmp_path: Path,
) -> None:
    result = _run_remote_tls_san_check(tmp_path, NODE_IP, "", openssl_x509_exit=1)

    assert result.returncode == 1
    assert "Failed to inspect server certificate SANs" in result.stderr
    assert f"server={NODE_IP}" in result.stderr
