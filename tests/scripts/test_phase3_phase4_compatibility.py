"""
Regression test for Phase 3/Phase 4 compatibility.

This test ensures that the default values for SUGARKUBE_SIMPLE_DISCOVERY and
SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT remain compatible with each other.

History:
- 2025-11-15: Phase 3 (simple discovery) and Phase 4 (skip service advertisement)
  were both enabled by default, causing discovery failure because nodes couldn't
  find services that weren't being advertised.

The fix: Change Phase 4 default to 0 (advertise services by default), making it
compatible with Phase 3's service browsing approach.
"""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k3s-discover.sh"


def test_phase3_phase4_defaults_are_compatible() -> None:
    """
    Test that Phase 3 and Phase 4 defaults are compatible.

    Phase 3 (SIMPLE_DISCOVERY=1) uses service browsing to find servers.
    Phase 4 (SKIP_SERVICE_ADVERTISEMENT=1) skips publishing services.

    These are incompatible: can't browse for services that aren't published.

    Valid combinations:
    - SIMPLE_DISCOVERY=1, SKIP_SERVICE_ADVERTISEMENT=0 (browse for advertised services) ✓
    - SIMPLE_DISCOVERY=0, SKIP_SERVICE_ADVERTISEMENT=0 (legacy discovery with advertisement) ✓
    - SIMPLE_DISCOVERY=0, SKIP_SERVICE_ADVERTISEMENT=1 (legacy discovery without advertisement) ✓
    - SIMPLE_DISCOVERY=1, SKIP_SERVICE_ADVERTISEMENT=1 (simple discovery without advertisement) ✗
    """
    script_content = SCRIPT.read_text(encoding="utf-8")
    lines = script_content.splitlines()

    simple_discovery_default = None
    skip_advertisement_default = None

    for line in lines:
        # Find SIMPLE_DISCOVERY default
        if 'SIMPLE_DISCOVERY="${SUGARKUBE_SIMPLE_DISCOVERY' in line:
            if ':-1}' in line:
                simple_discovery_default = 1
            elif ':-0}' in line:
                simple_discovery_default = 0

        # Find SKIP_SERVICE_ADVERTISEMENT default
        if 'SKIP_SERVICE_ADVERTISEMENT="${SUGARKUBE_SKIP_SERVICE_ADVERTISEMENT' in line:
            if ':-1}' in line:
                skip_advertisement_default = 1
            elif ':-0}' in line:
                skip_advertisement_default = 0

    assert simple_discovery_default is not None, \
        "Could not determine SIMPLE_DISCOVERY default value"
    assert skip_advertisement_default is not None, \
        "Could not determine SKIP_SERVICE_ADVERTISEMENT default value"

    # The incompatible combination is SIMPLE_DISCOVERY=1 with SKIP_SERVICE_ADVERTISEMENT=1
    # This means: "use service browsing" + "don't advertise services" = discovery fails
    is_incompatible = (simple_discovery_default == 1 and skip_advertisement_default == 1)

    assert not is_incompatible, (
        f"Phase 3/4 default combination is incompatible!\n"
        f"SIMPLE_DISCOVERY defaults to {simple_discovery_default}\n"
        f"SKIP_SERVICE_ADVERTISEMENT defaults to {skip_advertisement_default}\n"
        f"When SIMPLE_DISCOVERY=1 (use service browsing), "
        f"SKIP_SERVICE_ADVERTISEMENT must be 0 (advertise services).\n"
        f"Otherwise joining nodes cannot discover bootstrap nodes."
    )

    # Document the valid configuration for future reference
    if simple_discovery_default == 1:
        assert skip_advertisement_default == 0, (
            "When Phase 3 simple discovery is enabled (default=1), "
            "Phase 4 must advertise services (default=0)"
        )


def test_phase3_uses_service_browsing() -> None:
    """
    Verify that Phase 3 implementation actually uses service browsing.

    This documents the current implementation approach. If this changes to use
    pure NSS resolution (getent hosts), then Phase 4 can be safely enabled.
    """
    script_content = SCRIPT.read_text(encoding="utf-8")

    # Phase 3's discover_via_nss_and_api function should use select_server_candidate
    assert 'select_server_candidate' in script_content, \
        "Phase 3 implementation should use select_server_candidate"

    # select_server_candidate should use run_avahi_query for service browsing
    assert 'run_avahi_query' in script_content, \
        "Discovery should use run_avahi_query for service browsing"

    # run_avahi_query should use avahi-browse (via Python k3s_mdns_query module)
    assert 'k3s_mdns_query' in script_content or 'avahi-browse' in script_content, \
        "Service browsing should use avahi-browse"


def test_documentation_warns_about_incompatibility() -> None:
    """
    Verify that documentation warns users about the Phase 3/4 incompatibility.
    """
    doc_path = Path(__file__).resolve().parents[2] / "docs" / "raspi_cluster_setup.md"
    doc_content = doc_path.read_text(encoding="utf-8")

    # Documentation should mention the incompatibility
    phase4_section = None
    for i, line in enumerate(doc_content.splitlines()):
        if 'Phase 4:' in line and 'Service Advertisement' in line:
            # Read next 30 lines for the section
            phase4_section = '\n'.join(
                doc_content.splitlines()[i:i+30]
            )
            break

    assert phase4_section is not None, \
        "Could not find Phase 4 section in documentation"

    # Should mention incompatibility or dependency
    has_warning = (
        'incompatible' in phase4_section.lower() or
        'must also' in phase4_section.lower() or
        'requires' in phase4_section.lower() or
        'depends' in phase4_section.lower()
    )

    assert has_warning, (
        "Phase 4 documentation should warn about incompatibility with Phase 3 "
        "when service advertisement is disabled"
    )
