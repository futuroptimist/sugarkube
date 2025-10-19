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
