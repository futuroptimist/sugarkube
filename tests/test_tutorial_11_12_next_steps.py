"""Ensure tutorials 11 and 12 no longer reference unpublished guides."""

from __future__ import annotations

from pathlib import Path

DOC_11 = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "tutorials"
    / "tutorial-11-storage-migration-maintenance.md"
)

DOC_12 = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "tutorials"
    / "tutorial-12-contributing-new-features-automation.md"
)


def test_tutorial_11_promotes_available_tutorial_12() -> None:
    """Tutorial 11 should acknowledge Tutorial 12 is already published."""

    text = DOC_11.read_text(encoding="utf-8")
    assert (
        "(once published)" not in text
    ), "Tutorial 11 still frames Tutorial 12 as unpublished future work"
    assert (
        "Continue to [Tutorial 12: Contributing New Features and Automation]" in text
    ), "Tutorial 11 should direct readers to the published Tutorial 12 guide"


def test_tutorial_12_promotes_available_tutorial_13() -> None:
    """Tutorial 12 should acknowledge Tutorial 13 is already published."""

    text = DOC_12.read_text(encoding="utf-8")
    assert (
        "when it becomes available" not in text
    ), "Tutorial 12 still frames Tutorial 13 as future work"
    assert (
        "Advance to [Tutorial 13: Advanced Operations and Future Directions]" in text
    ), "Tutorial 12 should direct readers to the published Tutorial 13 guide"
