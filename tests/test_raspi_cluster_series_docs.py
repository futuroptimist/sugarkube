"""Tests to ensure the Raspberry Pi cluster series docs remain properly linked and discoverable."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_DOC = REPO_ROOT / "docs" / "index.md"
MANUAL_SETUP_DOC = REPO_ROOT / "docs" / "raspi_cluster_setup_manual.md"
QUICK_START_DOC = REPO_ROOT / "docs" / "raspi_cluster_setup.md"
OPERATIONS_DOC = REPO_ROOT / "docs" / "raspi_cluster_operations.md"


@pytest.fixture(scope="module")
def index_text() -> str:
    return INDEX_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def manual_setup_text() -> str:
    return MANUAL_SETUP_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def quick_start_text() -> str:
    return QUICK_START_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def operations_text() -> str:
    return OPERATIONS_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def series_section(index_text: str) -> str:
    """Extract the 'Raspberry Pi cluster series' section from index.md."""
    series_start = index_text.find("## Raspberry Pi cluster series")
    next_section = index_text.find("\n## ", series_start + 1)
    if next_section == -1:
        return index_text[series_start:]
    else:
        return index_text[series_start:next_section]


# Test series linkage from index.md
def test_index_lists_series_section(index_text: str) -> None:
    """The index should have a dedicated section for the Raspberry Pi cluster series."""
    assert "## Raspberry Pi cluster series" in index_text


def test_index_lists_all_three_docs(series_section: str) -> None:
    """The index should list all three docs in the series."""
    # Check all three docs are mentioned
    assert "raspi_cluster_setup_manual.md" in series_section
    assert "raspi_cluster_setup.md" in series_section
    assert "raspi_cluster_operations.md" in series_section


def test_index_describes_series_as_three_parts(series_section: str) -> None:
    """The index should describe the series as having three parts."""
    # Check that the series is described with numbered parts
    assert any(
        phrase in series_section for phrase in ["three-part", "3-part", "1.", "2.", "3."]
    ), "Series should be described as having three parts"


# Test that each doc declares its position in the series
def test_manual_setup_declares_part_1(manual_setup_text: str) -> None:
    """The manual setup doc should declare itself as Part 1 of 3."""
    assert "Part 1 of 3" in manual_setup_text or "Part 1 / 3" in manual_setup_text


def test_quick_start_declares_part_2(quick_start_text: str) -> None:
    """The quick start doc should declare itself as Part 2 of 3."""
    assert "Part 2 of 3" in quick_start_text or "Part 2 / 3" in quick_start_text


def test_operations_declares_part_3(operations_text: str) -> None:
    """The operations doc should declare itself as Part 3 of 3."""
    assert "Part 3 of 3" in operations_text or "Part 3 / 3" in operations_text


# Test forward/backward links between docs
def test_manual_setup_links_to_quick_start(manual_setup_text: str) -> None:
    """Part 1 should link to Part 2."""
    assert "raspi_cluster_setup.md" in manual_setup_text


def test_manual_setup_links_to_operations(manual_setup_text: str) -> None:
    """Part 1 should mention Part 3."""
    assert "raspi_cluster_operations.md" in manual_setup_text


def test_quick_start_links_to_manual(quick_start_text: str) -> None:
    """Part 2 should link back to Part 1."""
    assert "raspi_cluster_setup_manual.md" in quick_start_text


def test_quick_start_links_to_operations(quick_start_text: str) -> None:
    """Part 2 should link to Part 3."""
    assert "raspi_cluster_operations.md" in quick_start_text


def test_operations_links_to_quick_start(operations_text: str) -> None:
    """Part 3 should link back to Part 2."""
    assert "raspi_cluster_setup.md" in operations_text


def test_operations_mentions_manual(operations_text: str) -> None:
    """Part 3 should mention Part 1."""
    assert "raspi_cluster_setup_manual.md" in operations_text


# Test that each doc mentions the series
def test_manual_setup_mentions_series(manual_setup_text: str) -> None:
    """Part 1 should mention it's part of the Raspberry Pi cluster series."""
    assert "Raspberry Pi cluster series" in manual_setup_text


def test_quick_start_mentions_series(quick_start_text: str) -> None:
    """Part 2 should mention it's part of the Raspberry Pi cluster series."""
    assert "Raspberry Pi cluster series" in quick_start_text


def test_operations_mentions_series(operations_text: str) -> None:
    """Part 3 should mention it's part of the Raspberry Pi cluster series."""
    assert "Raspberry Pi cluster series" in operations_text
