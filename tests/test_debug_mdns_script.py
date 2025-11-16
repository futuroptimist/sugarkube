import os
import re
import subprocess
from pathlib import Path
from typing import Optional


SCRIPT = Path("logs/debug-mdns.sh")
STUB_BIN = Path("tests/fixtures/debug_mdns/bin")


def run_script(allowed_hosts: Optional[str] = None) -> str:
    env = os.environ.copy()
    env["PATH"] = f"{STUB_BIN}{os.pathsep}" + env.get("PATH", "")
    if allowed_hosts is not None:
        env["MDNS_ALLOWED_HOSTS"] = allowed_hosts
    result = subprocess.run(
        [SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def test_redacts_addresses_and_mac():
    output = run_script()

    assert "<REDACTED_IPV4>" in output
    assert "<REDACTED_MAC>" in output
    assert "<REDACTED_IPV6>" in output

    assert "192.168.10.5" not in output
    assert "10.0.0.5" not in output
    assert "aa:bb:cc:dd:ee:ff" not in output

    ipv4_pattern = re.compile(
        r"((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    )
    for match in ipv4_pattern.finditer(output):
        assert match.group(0) in {"0.0.0.0"}


def test_filters_avahi_output_to_allowlist_and_service():
    output = run_script()

    assert "sugarkube1.local" in output
    assert "printer.local" not in output
    assert "rogue.local _http._tcp" not in output
    assert "rogue.local _k3s-sugar-dev._tcp" in output


def test_allows_runtime_allowlist_override():
    output = run_script("special.local")

    assert "special.local" in output
    assert "sugarkube1.local" not in output
    assert "rogue.local _k3s-sugar-dev._tcp" in output

    allowed_section = [line for line in output.splitlines() if line.startswith(" - ")]
    assert allowed_section == [" - special.local"]
