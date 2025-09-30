"""Ensure tutorial "Next Steps" sections point to published guides."""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs" / "tutorials"

TUTORIAL_NEXT_STEPS = (
    (
        "tutorial-10-first-boot-verification-self-healing.md",
        "Advance to [Tutorial 11: Storage Migration and Long-Term Maintenance]",
    ),
    (
        "tutorial-04-version-control-collaboration.md",
        "Advance to [Tutorial 5: Programming for Operations with Python and Bash]",
    ),
    (
        "tutorial-07-kubernetes-container-fundamentals.md",
        "Advance to [Tutorial 8: Preparing a Sugarkube Development Environment]",
    ),
    (
        "tutorial-12-contributing-new-features-automation.md",
        "Advance to [Tutorial 13: Advanced Operations and Future Directions]",
    ),
)


@pytest.mark.parametrize("filename, expected_fragment", TUTORIAL_NEXT_STEPS)
def test_next_steps_reference_published_tutorial(filename: str, expected_fragment: str) -> None:
    text = (DOCS_DIR / filename).read_text(encoding="utf-8")
    assert (
        "when it becomes available" not in text
    ), "Next Steps should highlight published follow-up tutorials"
    assert expected_fragment in text, "Next Steps should link directly to the follow-up tutorial"
    if filename == "tutorial-10-first-boot-verification-self-healing.md":
        assert (
            "./tutorial-11-storage-migration-maintenance.md" in text
        ), "Tutorial 10 should link directly to the published Tutorial 11 guide"
