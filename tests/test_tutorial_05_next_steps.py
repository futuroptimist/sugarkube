"""Ensure Tutorial 5 no longer frames Tutorial 6 as future work."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "tutorials"
    / "tutorial-05-programming-for-operations.md"
)


def test_next_steps_reflect_published_tutorial_six() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "forthcoming" not in text.lower(), "Tutorial 5 still describes Tutorial 6 as forthcoming"
