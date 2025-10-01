"""Ensure Tutorial 1 points readers to the published follow-up guide."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "tutorials"
    / "tutorial-01-computing-foundations.md"
)

EXPECTED_FRAGMENT = (
    "Continue with the roadmap by reading [Tutorial 2: Navigating Linux and the " "Terminal]"
)


def test_next_steps_promotes_published_tutorial_two() -> None:
    """Tutorial 1 should acknowledge Tutorial 2 is already available."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "once it is published" not in text
    ), "Tutorial 1 still frames Tutorial 2 as unpublished future work"
    assert EXPECTED_FRAGMENT in text, "Tutorial 1 should link to the published Tutorial 2 guide"
