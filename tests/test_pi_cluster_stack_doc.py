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
    """CI download guidance should point to the grouped stack artifact layout."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "stl-pi_cluster_stack-${GITHUB_SHA}" in text
    assert "stl-${GITHUB_SHA}" in text
    for folder in ("printed/", "heatset/", "variants/"):
        assert folder in text


def test_stack_doc_heatset_guidance_is_post_print() -> None:
    """Remove the outdated pause-to-insert recommendation for heat-set inserts."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Pause after the first 2 mm to insert heat-set brass hardware" not in text
    assert "Install heat-set\n  inserts after printing" in text


def test_stack_doc_fan_mount_diameter_consistent() -> None:
    """The fan hole diameter guidance should consistently target M3 clearance."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Ø3.2–3.4" in text
    assert "M4/#6 pass-through" not in text
