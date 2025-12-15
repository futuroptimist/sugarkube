"""Ensure the stacked carrier doc ships the promised assembly guide."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "pi_cluster_stack.md"


def test_stack_doc_includes_bom_and_steps() -> None:
    """The spec should now include an assembly guide and bill of materials."""

    text = DOC_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "future work" not in lowered, "Stack doc still references future work"
    assert "## Bill of materials" in text, "Stack doc should publish a BOM section"
    assert "## Assembly sequence" in text, "Stack doc should outline the build steps"


def test_stack_doc_links_carrier_reference() -> None:
    """The doc should point builders to the existing carrier reference material."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "pi_cluster_carrier.md" in text, "Stack doc should cross-link the carrier field guide"


def test_stack_doc_deliverables_marked_shipped() -> None:
    """Deliverables section should no longer be labeled as future work."""

    text = DOC_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    assert (
        "## 12. deliverables checklist (for future implementation)" not in lowered
    ), "Stack doc still frames deliverables as future implementation"
    assert (
        "## 12. Deliverables checklist" in text
    ), "Stack doc should keep the deliverables checklist header"


def test_stack_doc_prefers_grouped_artifact() -> None:
    """The stacked carrier should point at the grouped STL artifact bundle."""

    text = DOC_PATH.read_text(encoding="utf-8")
    grouped = "stl-pi_cluster_stack-${GITHUB_SHA}"
    legacy = "stl-${GITHUB_SHA}"
    assert grouped in text, "Doc should reference the grouped pi_cluster_stack artifact"
    assert legacy in text, "Doc should keep the legacy monolithic artifact reference"
    assert text.find(grouped) < text.find(legacy), "Grouped artifact should be preferred over legacy"


def test_stack_doc_heatset_guidance_is_post_print() -> None:
    """The print prep section should no longer suggest mid-print insert installs by default."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "Pause after the first 2 mm to insert heat-set brass hardware" not in text
    ), "Print prep still suggests pausing mid-print for heat-set inserts"


def test_fan_mount_holes_use_consistent_diameter() -> None:
    """The fan hole diameter guidance should share one clearance target."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Ø3.4" in text, "Fan mount holes should call out the 3.4 mm M3 clearance"
    assert "Ø3.2" not in text, "Remove conflicting Ø3.2–3.4 ranges from the fan mount guidance"
