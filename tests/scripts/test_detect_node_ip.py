import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "configure_k3s_node_ip.sh"


def detect_ip(sample: str) -> str:
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--detect-ip-from-stdin"],
        input=sample.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode().strip()


def test_selects_first_ipv4_address():
    sample = """2: eth0    inet 192.168.10.5/24 brd 192.168.10.255 scope global eth0\n"""
    assert detect_ip(sample) == "192.168.10.5"


def test_ignores_additional_addresses_after_first_match():
    sample = """2: eth0    inet 192.168.10.5/24 brd 192.168.10.255 scope global eth0\n""" """
3: eth0    inet 192.168.10.25/24 brd 192.168.10.255 scope global secondary eth0\n"""
    assert detect_ip(sample) == "192.168.10.5"


def test_handles_leading_whitespace_and_tabs():
    sample = """  2: eth0\tinet 10.0.0.2/16 brd 10.0.255.255 scope global eth0\n"""
    assert detect_ip(sample) == "10.0.0.2"
