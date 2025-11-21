"""Ensure mDNS troubleshooting docs describe integration test prerequisites."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "mdns_troubleshooting.md"


def test_mdns_troubleshooting_mentions_getent_requirement() -> None:
    """The mDNS doc should call out getent/NSS requirements for integration runs."""
    text = DOC_PATH.read_text(encoding="utf-8").lower()
    assert "getent hosts" in text, "Document getent hosts usage for NSS validation"
    assert "integration test" in text, "Document integration harness expectations"
    assert "nss" in text, "Mention NSS configuration alongside getent guidance"
