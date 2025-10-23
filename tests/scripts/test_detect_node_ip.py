"""Tests for the configure_k3s_node_ip helper parser."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "configure_k3s_node_ip.sh"


def _run_parser(sample: str) -> subprocess.CompletedProcess[str]:
    command = textwrap.dedent(
        f"""
        set -euo pipefail
        source '{SCRIPT_PATH}'
        extract_primary_ipv4 <<'IPDATA'
        {sample}
IPDATA
        """
    )
    return subprocess.run(
        ["bash", "-c", command],
        check=False,
        text=True,
        capture_output=True,
    )


def test_extract_primary_ipv4_single_address() -> None:
    sample = """
        2: eth0    inet 192.168.0.20/24 brd 192.168.0.255 scope global dynamic eth0
           valid_lft 86378sec preferred_lft 86378sec
    """
    result = _run_parser(sample)
    assert result.returncode == 0
    assert result.stdout.strip() == "192.168.0.20"


def test_extract_primary_ipv4_prefers_first_entry() -> None:
    sample = """
        3: eth0    inet 10.10.0.5/24 brd 10.10.0.255 scope global eth0
           valid_lft 86388sec preferred_lft 86388sec
        3: eth0    inet 10.10.0.6/24 brd 10.10.0.255 scope global secondary eth0
           valid_lft 86388sec preferred_lft 86388sec
    """
    result = _run_parser(sample)
    assert result.returncode == 0
    assert result.stdout.strip() == "10.10.0.5"


def test_extract_primary_ipv4_missing_address() -> None:
    sample = """
        1: lo    inet6 ::1/128 scope host
           valid_lft forever preferred_lft forever
    """
    result = _run_parser(sample)
    assert result.returncode != 0
    assert result.stdout.strip() == ""
