"""Regression coverage for the stacked Pi carrier assembly guide."""

from __future__ import annotations

from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"
ASSEMBLY_DOC = DOCS_ROOT / "pi_cluster_stack_assembly.md"
STACK_SPEC_DOC = DOCS_ROOT / "pi_cluster_stack.md"
HARDWARE_INDEX = DOCS_ROOT / "hardware" / "index.md"


def test_assembly_doc_exists() -> None:
    """The dedicated assembly guide should ship with the repository."""

    assert ASSEMBLY_DOC.exists(), "Assembly guide missing; add docs/pi_cluster_stack_assembly.md"


def test_assembly_doc_sections() -> None:
    """The assembly guide should publish checklists and materials."""

    text = ASSEMBLY_DOC.read_text(encoding="utf-8")
    for heading in ("## Bill of materials", "## Assembly checklist", "## Tooling and consumables"):
        assert heading in text, f"Expected heading '{heading}' in docs/pi_cluster_stack_assembly.md"


def test_assembly_doc_links_design_spec() -> None:
    """Builders should be able to jump back to the underlying design spec."""

    text = ASSEMBLY_DOC.read_text(encoding="utf-8")
    assert (
        "pi_cluster_stack.md" in text
    ), "Assembly guide should link to docs/pi_cluster_stack.md for design constraints"


def test_hardware_index_links_assembly_doc() -> None:
    """Hardware landing page should cross-link the new guide."""

    index_text = HARDWARE_INDEX.read_text(encoding="utf-8")
    assert (
        "pi_cluster_stack_assembly.md" in index_text
    ), "docs/hardware/index.md should reference the stacked carrier assembly guide"


def test_design_spec_marks_deliverable_complete() -> None:
    """The spec's deliverables list should mark the assembly doc as shipped."""

    spec_text = STACK_SPEC_DOC.read_text(encoding="utf-8")
    assert (
        "- [x] Create user-facing assembly/BOM documentation" in spec_text
    ), "Stack design spec should mark the assembly/BOM doc deliverable as complete"
