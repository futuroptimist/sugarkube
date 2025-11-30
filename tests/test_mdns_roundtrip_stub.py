"""Guard the mDNS roundtrip test against skipping Avahi CLI coverage."""

from __future__ import annotations

from pathlib import Path


def test_mdns_roundtrip_does_not_skip_avahi_tools() -> None:
    """Ensure the integration test no longer relies on skip-based fallbacks."""

    bats_test = Path("tests/integration/mdns_roundtrip.bats")
    content = bats_test.read_text(encoding="utf-8")

    assert "hermetic stub fallback" not in content
    assert "avahi-publish not available" not in content
    assert "avahi-browse not available" not in content
    assert "avahi-resolve not available" not in content
