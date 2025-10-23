import subprocess
from pathlib import Path
import shlex

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "configure_k3s_node_ip.sh"


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
