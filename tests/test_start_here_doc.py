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


def test_start_here_doc_includes_persona_tabs() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        '=== "Hardware builders"' in text
    ), "Start-here guide should present a tab for hardware builders"
    assert (
        '=== "Software contributors"' in text
    ), "Start-here guide should present a tab for software contributors"


def test_start_here_doc_embeds_architecture_diagram() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "![Sugarkube architecture overview" in text
    ), "Start-here guide should embed an architecture diagram for quick orientation"
    assert (
        "images/sugarkube_diagram.svg" in text
    ), "Start-here guide should reference the shared architecture diagram asset"
    lines = text.splitlines()
    diagram_lines = [line for line in lines if "![Sugarkube architecture overview" in line]
    assert diagram_lines, "Diagram embed should reside on a single Markdown line"
    assert all(
        ")](images/sugarkube_diagram.svg)" in line or "(images/sugarkube_diagram.svg)" in line
        for line in diagram_lines
    ), "Diagram embed must reference the SVG on the same line to avoid broken links"
