"""Tests for discovery fail-open timeout configuration."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_failopen_timeout_configuration_exists() -> None:
    """Test that fail-open timeout configuration variables exist in k3s-discover.sh."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for the key configuration variables
    assert 'DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT' in script_content, \
        "DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT should be defined"
    assert 'DISCOVERY_FAILOPEN_TIMEOUT_SECS' in script_content, \
        "DISCOVERY_FAILOPEN_TIMEOUT_SECS should be defined"

    # Verify the configuration uses secure, environment-agnostic defaults
    lines = script_content.splitlines()

    # Find the configuration block
    config_block_start = -1
    for i, line in enumerate(lines):
        if 'Discovery fail-open configuration' in line or 'DISCOVERY_FAILOPEN' in line:
            config_block_start = i
            break

    assert config_block_start >= 0, "Should find fail-open configuration block"

    # Check that secure defaults exist in the config section
    config_section = '\n'.join(lines[config_block_start:config_block_start+30])
    assert 'DISCOVERY_FAILOPEN_DEFAULT=0' in config_section, \
        "DISCOVERY_FAILOPEN_DEFAULT should be 0 (opt-in only)"
    assert 'DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT=300' in config_section, \
        "DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT should be 300 seconds"
    assert 'ENVIRONMENT' not in config_section, \
        "Fail-open defaults should not branch on ENVIRONMENT"


def test_failopen_uses_environment_variable() -> None:
    """Test that SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT is respected."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Verify that SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT can override the default
    assert 'SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT' in script_content, \
        "Should respect SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT environment variable"

    # Check the pattern: TIMEOUT_SECS="${SUGARKUBE_...:-${DEFAULT}}"
    lines = script_content.splitlines()
    found_override_pattern = False

    for line in lines:
        if 'DISCOVERY_FAILOPEN_TIMEOUT_SECS' in line and 'SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT' in line:
            found_override_pattern = True
            break

    assert found_override_pattern, \
        "DISCOVERY_FAILOPEN_TIMEOUT_SECS should use SUGARKUBE_DISCOVERY_FAILOPEN_TIMEOUT with default fallback"
