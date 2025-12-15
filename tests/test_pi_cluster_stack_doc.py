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


def test_stack_doc_prefers_grouped_stl_artifact() -> None:
    """Builders should be guided toward the pi_cluster_stack-specific artifact bundle."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "stl-pi_cluster_stack-${GITHUB_SHA}" in text, "Grouped artifact should be recommended"
    assert "stl-${GITHUB_SHA}" in text, "Legacy monolithic artifact should remain documented"


def test_stack_doc_heatset_guidance_reflects_post_print_installs() -> None:
    """Heat-set inserts are installed after printing; avoid mid-print instructions here."""

    text = DOC_PATH.read_text(encoding="utf-8")
    flattened = " ".join(text.split())
    assert "Install heat-set inserts after printing" in flattened
    assert (
        "Pause after the first 2 mm to insert heat-set brass hardware" not in text
    ), "Stack doc still recommends pausing early for inserts"


def test_stack_doc_fan_mount_holes_are_consistent() -> None:
    """Fan mounting guidance should consistently describe the M3 clearance holes."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Ø3.2–3.4" in text, "Fan mount holes should cite the M3 clearance range"
    assert "M4/#6 pass-through" not in text, "Avoid conflicting oversized pass-through guidance"


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
