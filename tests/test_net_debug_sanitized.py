from pathlib import Path
import os
import re
import subprocess


SCRIPT = Path("scripts/net_debug_sanitized.sh")
STUB_BIN = Path("tests/fixtures/net_debug/bin")


def run_script(stage: str = "test-stage") -> str:
    env = os.environ.copy()
    env["PATH"] = f"{STUB_BIN}{os.pathsep}" + env.get("PATH", "")
    env["LOG_SALT"] = "0123456789abcdef"
    result = subprocess.run(
        [SCRIPT, stage],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def test_sanitizes_sensitive_tokens():
    output = run_script()

    mac_pattern = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
    assert not mac_pattern.search(output)

    ipv4_pattern = re.compile(r"((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)")
    for match in ipv4_pattern.finditer(output):
        assert match.group(0) in {"127.0.0.1", "0.0.0.0"}

    assert "Authorization: [REDACTED]" in output
    assert "Bearer abcdef12345" not in output


def test_mdns_count_and_instances_present():
    output = run_script("mdns-first-browse")
    assert "mdns.services._k3s-sugar-dev._tcp.count: 2" in output
    assert "mdns.active: yes" in output
    assert "mdns.services._k3s-sugar-dev._tcp.instances" in output


def test_stage_annotation_and_hash_stability():
    first_run = run_script("pre-election-backoff")
    second_run = run_script("pre-election-backoff")
    assert "stage: pre-election-backoff" in first_run
    assert "stage: pre-election-backoff" in second_run
    token_pattern = re.compile(
        r"(PUBLIC-[0-9a-f]{6}|host-[0-9a-f]{6}|10\.[0-9a-f]{6}|172\.[0-9a-f]{6}|"
        r"192\.168\.[0-9a-f]{6}|IPv6-[0-9a-f]{6}|MAC-[0-9a-f]{6})"
    )
    assert set(token_pattern.findall(first_run)) == set(token_pattern.findall(second_run))
