from pathlib import Path
import os
import re
import subprocess


SCRIPT = Path("logs/debug-mdns.sh")
STUB_BIN = Path("tests/fixtures/debug_mdns/bin")


def run_script(allowed_hosts=None) -> str:
    env = os.environ.copy()
    env["PATH"] = f"{STUB_BIN}{os.pathsep}" + env.get("PATH", "")
    if allowed_hosts is not None:
        env["MDNS_ALLOWED_HOSTS"] = " ".join(allowed_hosts)
    result = subprocess.run(
        [SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def test_redacts_addresses_and_filters_services():
    output = run_script()

    assert "<REDACTED_IPV4>" in output
    assert "<REDACTED_MAC>" in output
    assert "<REDACTED_IPV6>" in output

    assert "192.168.1.42" not in output
    assert "aa:bb:cc:dd:ee:ff" not in output
    assert "printer.local" not in output
    assert "unallowed.local" not in output


def test_allowlist_override_and_resolution_failures():
    output = run_script(["other.local", "missing.local"])

    assert "other.local" in output
    assert "missing.local" in output
    assert "<RESOLUTION_FAILED>" in output

    allowlist_lines = [line for line in output.splitlines() if line.startswith(" - ")]
    assert allowlist_lines == [" - other.local", " - missing.local"]


def test_avahi_browse_and_resolution_are_redacted():
    output = run_script()

    assert "<REDACTED_IP>" in output
    assert not re.search(r"\b10\.0\.0\.15\b", output)
    assert not re.search(r"\b192\.168\.1\.10\b", output)
