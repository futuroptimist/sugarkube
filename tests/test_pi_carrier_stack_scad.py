from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"


def test_pi_carrier_stack_imports_pi_carrier_module() -> None:
    """pi_carrier_stack should reuse the base module instead of cubes."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert "pi_carrier.scad" in source, "pi_carrier_stack should import pi_carrier.scad"
    assert re.search(r"\bpi_carrier\s*\(", source), "pi_carrier_stack should call pi_carrier()"
