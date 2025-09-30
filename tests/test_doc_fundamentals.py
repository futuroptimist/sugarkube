"""Tests for the shared fundamentals documentation section."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_fundamentals_doc_exists_and_links_key_primers() -> None:
    """Ensure the fundamentals index lists shared primers."""

    fundamentals_doc = REPO_ROOT / "docs" / "fundamentals" / "index.md"
    assert fundamentals_doc.exists(), "docs/fundamentals/index.md should exist"

    text = fundamentals_doc.read_text(encoding="utf-8")
    assert "personas:" in text and "hardware" in text and "software" in text

    for primer in (
        "../electronics_basics.md",
        "../solar_basics.md",
        "../insert_basics.md",
    ):
        assert primer in text, f"Fundamentals doc should link to {primer}"


def test_persona_indices_reference_fundamentals() -> None:
    """Hardware and software indices should direct readers to shared fundamentals."""

    fundamentals_link = "../fundamentals/index.md"
    hardware_text = (REPO_ROOT / "docs" / "hardware" / "index.md").read_text(encoding="utf-8")
    software_text = (REPO_ROOT / "docs" / "software" / "index.md").read_text(encoding="utf-8")

    assert fundamentals_link in hardware_text, "Hardware index should link to fundamentals"
    assert fundamentals_link in software_text, "Software index should link to fundamentals"
