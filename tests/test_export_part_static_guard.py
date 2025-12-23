from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"


def test_export_part_comparisons_use_string_literals() -> None:
    text = SCAD_PATH.read_text(encoding="utf-8")

    bad_patterns = (
        r"export_part\s*==\s*carrier_level",
        r"export_part\s*==\s*post(?!\s*\")",
    )

    for pattern in bad_patterns:
        assert not re.search(pattern, text), f"Found bare identifier match for {pattern}"


def test_export_part_defaults_are_documented() -> None:
    text = SCAD_PATH.read_text(encoding="utf-8")
    assert "carrier_level\"" in text
    assert "post\"" in text
