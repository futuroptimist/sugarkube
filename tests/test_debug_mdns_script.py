import os
import re
import subprocess
from pathlib import Path


SCRIPT = Path("logs/debug-mdns.sh")
STUB_BIN = Path("tests/fixtures/debug_mdns/bin")
SAFE_IPV4 = {"0.0.0.0", "224.0.0.251"}


def run_script(env_overrides=None) -> str:
    env = os.environ.copy()
    env["PATH"] = f"{STUB_BIN}{os.pathsep}" + env.get("PATH", "")
    env.setdefault("MDNS_ALLOWED_HOSTS", "allowed.local fail.local")
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        [SCRIPT],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def test_sanitizes_sensitive_tokens_and_filters_hosts():
    output = run_script()

    assert "secret-host.local" not in output
    assert "198.51.100.4" not in output
    assert "192.0.2.23" not in output
    assert "10.0.0.5" not in output

    assert "allowed.local    <REDACTED_IP>" in output
    assert "fail.local    <RESOLUTION_FAILED>" in output

    assert "<REDACTED_IPV4>" in output
    assert "<REDACTED_IPV6>" in output
    assert "<REDACTED_MAC>" in output
    assert "_k3s-sugar-dev._tcp" in output

    ipv4_pattern = re.compile(r"\b((?:[0-9]{1,3}\.){3}[0-9]{1,3})\b")
    for match in ipv4_pattern.finditer(output):
        assert match.group(1) in SAFE_IPV4

    mac_pattern = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
    assert not mac_pattern.search(output)


def test_allowlist_override_changes_output():
    output = run_script({"MDNS_ALLOWED_HOSTS": "alpha.local beta.local"})

    assert "alpha.local    <REDACTED_IP>" in output
    assert "beta.local    <REDACTED_IP>" in output
    assert "allowed.local" not in output
    assert "secret-host.local" not in output

    # Even with a strict allowlist, the k3s service is always kept
    assert "_k3s-sugar-dev._tcp" in output

    ipv4_pattern = re.compile(r"\b((?:[0-9]{1,3}\.){3}[0-9]{1,3})\b")
    for match in ipv4_pattern.finditer(output):
        assert match.group(1) in SAFE_IPV4
