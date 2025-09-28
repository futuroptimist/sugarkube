"""Ensure the tutorial roadmap reflects shipped guides."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "tutorials" / "index.md"


def test_tutorial_index_acknowledges_published_guides() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "Each entry will eventually become its own standalone guide" not in text
    ), "Tutorial roadmap still frames guides as future work"
    assert (
        "Every entry links to a maintained standalone guide" in text
    ), "Tutorial roadmap should confirm each guide is already published"
