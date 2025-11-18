"""Tests for SUGARKUBE_SIMPLE_DISCOVERY feature flag (Phase 3)."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_simple_discovery_variable_defined() -> None:
    """Test that SIMPLE_DISCOVERY variable is defined in k3s-discover.sh."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for the variable definition
    assert 'SIMPLE_DISCOVERY="${SUGARKUBE_SIMPLE_DISCOVERY' in script_content, \
        "SIMPLE_DISCOVERY should be defined from SUGARKUBE_SIMPLE_DISCOVERY"

    # Verify default is 1 (new behavior enabled by default)
    lines = script_content.splitlines()
    found_default = False

    for line in lines:
        if 'SIMPLE_DISCOVERY=' in line and 'SUGARKUBE_SIMPLE_DISCOVERY' in line:
            # Should default to 1
            if ':-1}' in line:
                found_default = True
                break

    assert found_default, "SIMPLE_DISCOVERY should default to 1 (simplified discovery enabled by default)"


def test_discover_via_nss_and_api_function_exists() -> None:
    """Test that discover_via_nss_and_api function is defined and uses service browsing."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for function definition
    assert 'discover_via_nss_and_api()' in script_content, \
        "discover_via_nss_and_api function should be defined"

    # Verify it uses select_server_candidate for proper service browsing
    lines = script_content.splitlines()
    in_function = False
    found_service_browse = False
    found_api_check = False

    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True

        if in_function and 'select_server_candidate' in line:
            found_service_browse = True

        if in_function and 'wait_for_remote_api_ready' in line:
            found_api_check = True

        # Exit function scope at next function definition
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break

    assert found_service_browse, "Function should use select_server_candidate for mDNS service browsing"
    assert found_api_check, "Function should use wait_for_remote_api_ready to check API"


def test_simple_discovery_uses_service_browsing() -> None:
    """Test that simple discovery uses mDNS service browsing instead of hardcoded hostnames."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find the function and verify it uses service browsing
    in_function = False
    found_service_browse = False
    found_hardcoded_pattern = False

    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True

        if in_function:
            # Check for proper service browsing
            if 'select_server_candidate' in line:
                found_service_browse = True

            # Check that it doesn't use hardcoded hostname iteration
            if 'sugarkube' in line and '${idx}' in line and '.local' in line:
                found_hardcoded_pattern = True

        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break

    assert found_service_browse, "Function should use select_server_candidate for mDNS service browsing"
    assert not found_hardcoded_pattern, "Function should NOT iterate through hardcoded sugarkube{0..N}.local hostnames"


def test_simple_discovery_conditional_in_main_flow() -> None:
    """Test that main flow checks SIMPLE_DISCOVERY flag."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for conditional that checks SIMPLE_DISCOVERY
    assert 'SIMPLE_DISCOVERY' in script_content and '= "1"' in script_content, \
        "Main flow should check if SIMPLE_DISCOVERY = 1"

    lines = script_content.splitlines()
    found_conditional = False
    found_function_call = False

    for i, line in enumerate(lines):
        # Look for the conditional check
        if 'SIMPLE_DISCOVERY' in line and '= "1"' in line and 'if' in line:
            found_conditional = True

            # Check that discover_via_nss_and_api is called nearby
            for j in range(i, min(i+30, len(lines))):
                if 'discover_via_nss_and_api' in lines[j]:
                    found_function_call = True
                    break

            if found_function_call:
                break

    assert found_conditional, "Should have conditional checking SIMPLE_DISCOVERY = 1"
    assert found_function_call, "Should call discover_via_nss_and_api when enabled"


def test_simple_discovery_handles_bootstrap() -> None:
    """Test that simple discovery handles bootstrap case when no token present."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find the discover_via_nss_and_api function
    in_function = False
    found_token_check = False
    found_bootstrap_path = False

    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True

        if in_function:
            # Check for TOKEN_PRESENT check (either = 0 or -eq 0)
            if 'TOKEN_PRESENT' in line and ('= 0' in line or '-eq 0' in line):
                found_token_check = True

            # Check for bootstrap mention
            if found_token_check and 'bootstrap' in line.lower():
                found_bootstrap_path = True
                break

        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break

    assert found_token_check, "Function should check TOKEN_PRESENT"
    assert found_bootstrap_path, "Function should handle bootstrap case when no token"


def test_simple_discovery_no_hardcoded_hostnames() -> None:
    """Test that simple discovery does not hardcode hostname patterns."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find the function and verify it doesn't hardcode hostnames
    in_function = False
    uses_service_discovery = False
    has_hostname_loop = False

    for i, line in enumerate(lines):
        if 'discover_via_nss_and_api()' in line:
            in_function = True

        if in_function:
            # Should use service discovery
            if 'select_server_candidate' in line:
                uses_service_discovery = True

            # Should not have hostname iteration based on SERVERS_DESIRED
            if 'seq 0' in line and 'server_count' in line:
                has_hostname_loop = True

        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'discover_via_nss_and_api' not in line:
            break

    assert uses_service_discovery, "Function should use mDNS service discovery"
    assert not has_hostname_loop, "Function should not iterate through hardcoded hostname counts"


def test_phase_3_comment_present() -> None:
    """Test that Phase 3 comments are present for documentation."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for Phase 3 documentation comments
    assert 'Phase 3:' in script_content or 'phase 3' in script_content.lower(), \
        "Should have Phase 3 documentation comments"

    # Verify it mentions service browsing (not NSS/direct resolution)
    lines = script_content.splitlines()
    phase3_mentioned = False

    for line in lines:
        if 'Phase 3' in line and ('service browsing' in line.lower() or 'mdns' in line.lower()):
            phase3_mentioned = True
            break

    assert phase3_mentioned, "Phase 3 comments should mention mDNS service browsing"
