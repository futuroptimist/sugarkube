from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "start-here.md"


def test_start_here_doc_exists() -> None:
    assert DOC_PATH.exists(), "docs/start-here.md is missing; create the onboarding entry point"


def test_start_here_doc_lists_tracks() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    required_headings = [
        "## 15-minute tour",
        "## Day-one contributor checklist",
        "## Advanced references",
    ]
    for heading in required_headings:
        assert heading in text, f"Expected heading '{heading}' in docs/start-here.md"


def test_start_here_doc_cross_links_resources() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    required_links = [
        "docs/index.md",
        "docs/tutorials/index.md",
        "docs/pi_image_quickstart.md",
        "docs/pi_image_contributor_guide.md",
    ]
    for link in required_links:
        assert link in text, f"Expected reference to '{link}' in docs/start-here.md"
