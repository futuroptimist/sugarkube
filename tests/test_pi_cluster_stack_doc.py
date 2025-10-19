from __future__ import annotations

from pathlib import Path

doc_path = Path(__file__).resolve().parents[1] / "docs" / "pi_cluster_stack.md"


def test_pi_cluster_stack_doc_exists() -> None:
    assert doc_path.exists(), "docs/pi_cluster_stack.md should exist for the stacked carrier"


def test_pi_cluster_stack_doc_adds_assembly_sections() -> None:
    text = doc_path.read_text(encoding="utf-8")
    expected_headings = [
        "## Assembly guide",
        "### Prepare the carriers",
        "### Install the columns",
        "### Mount the fan wall",
        "## Bill of materials",
    ]
    for heading in expected_headings:
        assert (
            heading in text
        ), f"Expected heading '{heading}' so the assembly/BOM guide is no longer future work"


def test_pi_cluster_stack_doc_references_cli_tools() -> None:
    text = doc_path.read_text(encoding="utf-8")
    assert (
        "sugarkube pi flash" in text
    ), "Assembly guide should reference the unified CLI for flashing images"
    assert (
        "sugarkube pi smoke" in text
    ), "Assembly guide should reference the smoke test after assembly"


def test_pi_cluster_stack_doc_removes_future_work_language() -> None:
    text = doc_path.read_text(encoding="utf-8")
    assert "future work" not in text.lower(), "Assembly guide should not mention future work"
