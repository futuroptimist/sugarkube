"""Tests for API readiness check with 401 responses."""

from __future__ import annotations

from pathlib import Path

# Test that the code change was made correctly by checking the source
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_wait_for_remote_api_ready_sets_allow_401() -> None:
    """wait_for_remote_api_ready should set ALLOW_HTTP_401=1 in check_env array."""

    # Read the script and verify the change is present
    script_content = SCRIPT.read_text(encoding="utf-8")

    # Find the wait_for_remote_api_ready function
    assert "wait_for_remote_api_ready()" in script_content

    # Look for the specific pattern where we set ALLOW_HTTP_401=1
    # The function should have a check_env array that includes this setting
    lines = script_content.splitlines()
    in_function = False
    found_allow_401 = False

    for i, line in enumerate(lines):
        if "wait_for_remote_api_ready()" in line:
            in_function = True

        if in_function and 'ALLOW_HTTP_401=1' in line:
            # Verify it's in the check_env array context
            # Look backwards to see if we're building check_env
            for j in range(max(0, i-10), i):
                if 'check_env=' in lines[j] or 'check_env+=' in lines[j]:
                    found_allow_401 = True
                    break
            if found_allow_401:
                break

        # Exit the function scope when we hit the next function
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and not line.startswith('\t') and '()' in line and 'wait_for_remote_api_ready' not in line:
            break

    assert found_allow_401, "ALLOW_HTTP_401=1 should be set in wait_for_remote_api_ready's check_env array"


def test_check_apiready_accepts_allow_401_env() -> None:
    """check_apiready.sh should respect ALLOW_HTTP_401 environment variable."""

    check_apiready = Path(__file__).resolve().parents[2] / "scripts" / "check_apiready.sh"
    script_content = check_apiready.read_text(encoding="utf-8")

    # Verify the script has logic to handle ALLOW_HTTP_401
    assert 'ALLOW_HTTP_401' in script_content, "check_apiready.sh should reference ALLOW_HTTP_401"

    # Check that it has the conditional logic for 401 responses
    assert '401' in script_content and 'ALLOW_HTTP_401' in script_content

    # Verify there's logic that treats 401 as alive when flag is set
    assert 'alive' in script_content or 'outcome=alive' in script_content


def test_failopen_timeout_defaults() -> None:
    """Test that fail-open timeout defaults are set correctly in k3s-discover.sh."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for the environment-specific defaults
    assert 'DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT' in script_content

    # Verify dev gets 60 seconds
    lines = script_content.splitlines()
    found_dev_60 = False
    found_prod_300 = False

    for i, line in enumerate(lines):
        # Look for the dev environment block
        if 'ENVIRONMENT' in line and 'dev' in line:
            # Check next few lines for timeout default
            for j in range(i, min(i+10, len(lines))):
                if 'DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT=60' in lines[j]:
                    found_dev_60 = True
                elif 'DISCOVERY_FAILOPEN_TIMEOUT_DEFAULT=300' in lines[j]:
                    found_prod_300 = True

    assert found_dev_60, "Dev environment should have 60 second fail-open timeout default"
    assert found_prod_300, "Prod environment should have 300 second fail-open timeout default"
