import os
import subprocess
from pathlib import Path
import shlex

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "configure_k3s_node_ip.sh"
TLS_TEMPLATE = (
    REPO_ROOT
    / "systemd"
    / "etc"
    / "rancher"
    / "k3s"
    / "config.yaml.d"
    / "10-sugarkube-tls.yaml"
)


def run_parser(sample: str) -> str:
    command = (
        f"source {shlex.quote(str(SCRIPT_PATH))} >/dev/null 2>&1; "
        "select_primary_ipv4_from_ip_output <<'EOF'\n"
        f"{sample}\nEOF"
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", command],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def test_select_primary_ipv4_prefers_first_inet():
    sample = "2: eth0    inet 192.168.10.15/24 brd 192.168.10.255 scope global eth0"
    assert run_parser(sample) == "192.168.10.15"


def test_select_primary_ipv4_skips_ipv6_and_secondary_entries():
    sample = "\n".join(
        [
            "2: eth0    inet6 fe80::ba27:ebff:fe12:3456/64 scope link",
            "2: eth0    inet 10.0.0.5/16 brd 10.0.255.255 scope global eth0",
            "3: eth0    inet 10.0.1.9/24 brd 10.0.1.255 scope global secondary eth0",
        ]
    )
    assert run_parser(sample) == "10.0.0.5"


def test_select_primary_ipv4_handles_extra_spacing():
    sample = "5: eth1    inet   172.16.1.20/24   brd 172.16.1.255   scope global   eth1"
    assert run_parser(sample) == "172.16.1.20"


def render_tls_config(tmp_path, regaddr):
    env = os.environ.copy()
    env.update(
        {
            "LOG_DIR": str(tmp_path / "log"),
            "SUGARKUBE_LOG_DIR": str(tmp_path / "log"),
            "TLS_SAN_TEMPLATE_PATH": str(TLS_TEMPLATE),
            "K3S_CONFIG_DIR": str(tmp_path / "etc" / "rancher" / "k3s"),
        }
    )
    env.pop("SUGARKUBE_API_REGADDR", None)
    if regaddr is not None:
        env["SUGARKUBE_API_REGADDR"] = regaddr
    command = (
        f"source {shlex.quote(str(SCRIPT_PATH))} >/dev/null 2>&1; "
        "render_tls_san_config"
    )
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", command],
        check=True,
        env=env,
        text=True,
    )
    dest = tmp_path / "etc" / "rancher" / "k3s" / "config.yaml.d" / "10-sugarkube-tls.yaml"
    return dest.read_text().splitlines()


def test_render_tls_config_skips_empty_registration(tmp_path):
    lines = render_tls_config(tmp_path, None)
    assert lines == ["tls-san:", '  - "sugarkube0.local"']


def test_render_tls_config_includes_registration_address(tmp_path):
    lines = render_tls_config(tmp_path, "vip.internal")
    assert lines == [
        "tls-san:",
        '  - "sugarkube0.local"',
        '  - "vip.internal"',
    ]
