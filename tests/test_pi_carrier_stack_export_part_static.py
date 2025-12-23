from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
STACK_POST_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_stack_post.scad"


def test_stack_exports_define_string_tokens() -> None:
    text = STACK_SCAD.read_text()
    assert "export_part_carrier_level = \"carrier_level\";" in text
    assert "export_part_post = \"post\";" in text
    assert "export_part_assembly = \"assembly\";" in text
    assert "export_part_resolved" in text


def test_stack_export_part_comparisons_use_strings() -> None:
    text = "\n".join(
        line for line in STACK_SCAD.read_text().splitlines() if not line.strip().startswith("//")
    )
    for bad_pattern in (
        r"export_part\s*==\s*carrier_level",
        r"export_part\s*==\s*post",
        r"export_part\s*=\s*carrier_level",
    ):
        assert re.search(bad_pattern, text) is None

    assert re.search(r"export_part_resolved\s*==\s*export_part_carrier_level", text)
    assert re.search(r"export_part_resolved\s*==\s*export_part_post", text)


def test_stack_post_guards_against_bare_carrier_level() -> None:
    text = STACK_POST_SCAD.read_text()
    assert "carrier_level = \"carrier_level\";" in text
