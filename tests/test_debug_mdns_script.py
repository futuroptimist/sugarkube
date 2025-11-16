import os
import re
import subprocess
from pathlib import Path


SCRIPT = Path("logs/debug-mdns.sh")
STUB_BIN = Path("tests/fixtures/debug_mdns/bin")


def run_script(env_overrides: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env["PATH"] = f"{STUB_BIN}{os.pathsep}" + env.get("PATH", "")
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


def test_redacts_addresses_and_filters_services() -> None:
    output = run_script()

    assert "<REDACTED_IPV4>" in output
    assert "<REDACTED_IPV6>" in output
    assert "<REDACTED_MAC>" in output

    assert "unlisted.local" not in output
    # _k3s-sugar-dev is always allowed
    assert "_k3s-sugar-dev._tcp" in output
    # custom host appears in browse output but is not in default allowlist
    assert "custom.local" not in output

    ipv4_pattern = re.compile(r"((25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)\\.){3}(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)")
    for match in ipv4_pattern.finditer(output):
        assert match.group(0) in {"0.0.0.0"}

    mac_pattern = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
    assert not mac_pattern.search(output)


def test_allowlist_override_is_used() -> None:
    output = run_script({"MDNS_ALLOWED_HOSTS": "custom.local"})

    assert "custom.local    <REDACTED_IP>" in output
    assert " - custom.local" in output
    assert "sugarkube1.local    <REDACTED_IP>" not in output
