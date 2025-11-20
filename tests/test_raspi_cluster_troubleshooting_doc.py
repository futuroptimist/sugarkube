"""Tests to ensure the Raspberry Pi cluster troubleshooting doc is properly linked."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TROUBLESHOOTING_DOC = REPO_ROOT / "docs" / "raspi_cluster_troubleshooting.md"
SETUP_DOC = REPO_ROOT / "docs" / "raspi_cluster_setup.md"
OPERATIONS_DOC = REPO_ROOT / "docs" / "raspi_cluster_operations.md"


@pytest.fixture(scope="module")
def troubleshooting_text() -> str:
    return TROUBLESHOOTING_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def setup_text() -> str:
    return SETUP_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def operations_text() -> str:
    return OPERATIONS_DOC.read_text(encoding="utf-8")


# Test that troubleshooting doc exists and has required content
def test_troubleshooting_doc_exists() -> None:
    """The troubleshooting doc should exist."""
    assert TROUBLESHOOTING_DOC.exists()


def test_troubleshooting_has_personas(troubleshooting_text: str) -> None:
    """The troubleshooting doc should have persona front matter."""
    assert "personas:" in troubleshooting_text
    assert "hardware" in troubleshooting_text or "software" in troubleshooting_text


def test_troubleshooting_has_title(troubleshooting_text: str) -> None:
    """The troubleshooting doc should have a clear title."""
    assert "Troubleshooting" in troubleshooting_text
    assert "Raspberry Pi" in troubleshooting_text


def test_troubleshooting_describes_log_types(troubleshooting_text: str) -> None:
    """The troubleshooting doc should describe different log types."""
    # Should mention up logs and mDNS logs
    assert "logs/up/" in troubleshooting_text.lower()
    assert "mdns" in troubleshooting_text.lower()
    assert "sanitized" in troubleshooting_text.lower() or "SAVE_DEBUG_LOGS" in troubleshooting_text


def test_troubleshooting_has_failure_scenarios(troubleshooting_text: str) -> None:
    """The troubleshooting doc should have multiple failure scenarios."""
    # Should have at least 3 scenarios (requirement was 3-5)
    scenario_count = troubleshooting_text.count("## Scenario") + troubleshooting_text.count("### Scenario")
    assert scenario_count >= 3, f"Expected at least 3 scenarios, found {scenario_count}"


def test_troubleshooting_scenarios_have_structure(troubleshooting_text: str) -> None:
    """Each scenario should describe what to look for."""
    # Each scenario should mention logs and next steps
    assert "which logs to inspect" in troubleshooting_text.lower() or "logs to inspect" in troubleshooting_text.lower()
    assert "next steps" in troubleshooting_text.lower()
    assert "example" in troubleshooting_text.lower() or "pattern" in troubleshooting_text.lower()


# Test that setup doc links to troubleshooting doc
def test_setup_links_to_troubleshooting(setup_text: str) -> None:
    """The setup doc should link to the troubleshooting guide."""
    assert "raspi_cluster_troubleshooting.md" in setup_text


def test_setup_troubleshooting_link_is_in_context(setup_text: str) -> None:
    """The setup doc troubleshooting link should be near logging or troubleshooting sections."""
    # Find the link and check nearby context
    link_index = setup_text.find("raspi_cluster_troubleshooting.md")
    assert link_index > 0, "Link not found in setup doc"
    
    # Check context around the link (500 chars before and after)
    context_start = max(0, link_index - 500)
    context_end = min(len(setup_text), link_index + 500)
    context = setup_text[context_start:context_end].lower()
    
    # Should be near logging, troubleshooting, or debug content
    assert any(
        keyword in context
        for keyword in ["log", "troubleshoot", "debug", "issue", "fail", "error"]
    ), "Link should be near relevant context"


# Test that operations doc links to troubleshooting doc
def test_operations_links_to_troubleshooting(operations_text: str) -> None:
    """The operations doc should link to the troubleshooting guide."""
    assert "raspi_cluster_troubleshooting.md" in operations_text


def test_operations_troubleshooting_link_is_in_context(operations_text: str) -> None:
    """The operations doc troubleshooting link should be near logging sections."""
    # Find the link and check nearby context
    link_index = operations_text.find("raspi_cluster_troubleshooting.md")
    assert link_index > 0, "Link not found in operations doc"
    
    # Check context around the link (500 chars before and after)
    context_start = max(0, link_index - 500)
    context_end = min(len(operations_text), link_index + 500)
    context = operations_text[context_start:context_end].lower()
    
    # Should be near logging content
    assert any(
        keyword in context
        for keyword in ["log", "sanitized", "debug", "save-logs", "troubleshoot"]
    ), "Link should be near relevant context"


# Test that troubleshooting doc links back to related docs
def test_troubleshooting_links_to_setup(troubleshooting_text: str) -> None:
    """The troubleshooting doc should reference the setup guide."""
    assert "raspi_cluster_setup.md" in troubleshooting_text


def test_troubleshooting_links_to_operations(troubleshooting_text: str) -> None:
    """The troubleshooting doc should reference the operations guide."""
    assert "raspi_cluster_operations.md" in troubleshooting_text


def test_troubleshooting_links_to_mdns_guide(troubleshooting_text: str) -> None:
    """The troubleshooting doc should reference the mDNS troubleshooting guide."""
    assert "mdns_troubleshooting.md" in troubleshooting_text
