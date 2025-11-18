"""Tests for SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT feature flag (Phase 4)."""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_skip_service_advertisement_variable_defined() -> None:
    """Test that SKIP_SERVICE_ADVERTISEMENT variable is defined in k3s-discover.sh."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for the variable definition
    assert 'SKIP_SERVICE_ADVERTISEMENT="${SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT' in script_content, \
        "SKIP_SERVICE_ADVERTISEMENT should be defined from SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT"

    # Verify default is 0 (service advertisement enabled by default)
    lines = script_content.splitlines()
    found_default = False

    for line in lines:
        if 'SKIP_SERVICE_ADVERTISEMENT=' in line and 'SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT' in line:
            # Should default to 0 (advertisement enabled)
            if ':-0}' in line:
                found_default = True
                break

    assert found_default, "SKIP_SERVICE_ADVERTISEMENT should default to 0 (service advertisement enabled by default)"


def test_publish_api_service_checks_flag() -> None:
    """Test that publish_api_service checks SKIP_SERVICE_ADVERTISEMENT flag."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find publish_api_service function
    in_function = False
    found_skip_check = False
    found_early_return = False

    for i, line in enumerate(lines):
        if 'publish_api_service()' in line:
            in_function = True

        if in_function:
            # Look for the skip check
            if 'SKIP_SERVICE_ADVERTISEMENT' in line and '= "1"' in line:
                found_skip_check = True

                # Check for early return nearby
                for j in range(i, min(i+5, len(lines))):
                    if 'return 0' in lines[j]:
                        found_early_return = True
                        break

                if found_early_return:
                    break

        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'publish_api_service' not in line:
            break

    assert found_skip_check, "publish_api_service should check SKIP_SERVICE_ADVERTISEMENT flag"
    assert found_early_return, "publish_api_service should return early when flag is set"


def test_publish_bootstrap_service_checks_flag() -> None:
    """Test that publish_bootstrap_service checks SKIP_SERVICE_ADVERTISEMENT flag."""

    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    # Find publish_bootstrap_service function
    in_function = False
    found_skip_check = False
    found_early_return = False

    for i, line in enumerate(lines):
        if 'publish_bootstrap_service()' in line:
            in_function = True

        if in_function:
            # Look for the skip check
            if 'SKIP_SERVICE_ADVERTISEMENT' in line and '= "1"' in line:
                found_skip_check = True

                # Check for early return nearby
                for j in range(i, min(i+5, len(lines))):
                    if 'return 0' in lines[j]:
                        found_early_return = True
                        break

                if found_early_return:
                    break

        # Exit function scope
        if in_function and i > 0 and line.strip() and not line.startswith(' ') and \
           not line.startswith('\t') and '()' in line and 'publish_bootstrap_service' not in line:
            break

    assert found_skip_check, "publish_bootstrap_service should check SKIP_SERVICE_ADVERTISEMENT flag"
    assert found_early_return, "publish_bootstrap_service should return early when flag is set"


def test_skip_service_advertisement_logs_when_skipped() -> None:
    """Test that script logs when service advertisement is skipped."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Verify logging when skipped
    assert 'service_advertisement_skipped' in script_content, \
        "Should log event=service_advertisement_skipped when advertisement is skipped"

    # Should mention the reason
    assert 'SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1' in script_content, \
        "Log message should mention SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT=1"


def test_phase_4_comment_present() -> None:
    """Test that Phase 4 comments are present for documentation."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # Check for Phase 4 documentation comments
    assert 'Phase 4:' in script_content or 'phase 4' in script_content.lower(), \
        "Should have Phase 4 documentation comments"

    # Verify it mentions service advertisement
    lines = script_content.splitlines()
    phase4_mentioned = False

    for line in lines:
        if 'Phase 4' in line and 'service' in line.lower() and 'advertisement' in line.lower():
            phase4_mentioned = True
            break

    assert phase4_mentioned, "Phase 4 comments should mention service advertisement"


def test_phase_4_preserves_local_resolution() -> None:
    """Test that Phase 4 documentation emphasizes .local resolution still works."""

    script_content = SCRIPT.read_text(encoding="utf-8")

    # When service advertisement is skipped, .local resolution should still work
    # This is documented in the roadmap - Avahi's host records are sufficient
    # The implementation should not break NSS resolution

    # Verify that getent and NSS resolution code is still present
    assert 'getent hosts' in script_content or 'getent ahosts' in script_content, \
        "NSS resolution via getent should still be available when service advertisement is skipped"
