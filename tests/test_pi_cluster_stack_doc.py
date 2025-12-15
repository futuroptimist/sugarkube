"""Ensure the stacked carrier doc ships the promised assembly guide."""
from __future__ import annotations
import re
from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "pi_cluster_stack.md"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_stack_doc_includes_bom_and_steps() -> None:
    """The spec should now include an assembly guide and bill of materials."""

    text = _read_doc()
    lowered = text.lower()
    assert "future work" not in lowered, "Stack doc still references future work"
    assert "## Bill of materials" in text, "Stack doc should publish a BOM section"
    assert "## Assembly sequence" in text, "Stack doc should outline the build steps"


def test_stack_doc_links_carrier_reference() -> None:
    """The doc should point builders to the existing carrier reference material."""

    text = _read_doc()
    assert "pi_cluster_carrier.md" in text, "Stack doc should cross-link the carrier field guide"


def test_stack_doc_deliverables_marked_shipped() -> None:
    """Deliverables section should no longer be labeled as future work."""

    text = _read_doc()
    lowered = text.lower()
    assert (
        "## 12. deliverables checklist (for future implementation)" not in lowered
    ), "Stack doc still frames deliverables as future implementation"
    assert (
        "## 12. Deliverables checklist" in text
    ), "Stack doc should keep the deliverables checklist header"


def test_stack_doc_prefers_grouped_artifacts() -> None:
    """Ensure the stacked carrier points to the grouped STL bundle before the legacy artifact."""

    text = _read_doc()
    assert (
        "stl-pi_cluster_stack-${GITHUB_SHA}" in text
    ), "Grouped stack-specific artifact should be referenced"
    assert "stl-${GITHUB_SHA}" in text, "Legacy monolithic artifact should still be noted"


def test_stack_doc_heatset_guidance_after_print() -> None:
    """Heat-set inserts should be described as post-print installations."""

    text = _read_doc()
    assert (
        "Pause after the first 2" not in text
    ), "Outdated mid-print insert guidance should be removed"
    assert "soldering iron" in text, "Doc should describe post-print heat-set installation"


def test_stack_doc_consistent_fan_hole_range() -> None:
    """Fan mounting holes should use a single documented clearance range."""

    text = _read_doc()
    fan_lines = [line for line in text.splitlines() if "fan" in line.lower() and "Ø" in line]
    ranges = re.findall(r"Ø[0-9.]+–[0-9.]+", "\n".join(fan_lines))
    assert ranges, "Fan hole diameter range should be documented"
    assert (
        len(set(ranges)) == 1
    ), "Fan hole diameter ranges should be consistent across sections"
