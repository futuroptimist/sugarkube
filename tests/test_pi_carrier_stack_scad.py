from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
PI_CARRIER_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier.scad"
FAN_WALL_PATH = REPO_ROOT / "cad" / "pi_cluster" / "fan_wall.scad"
DIMENSIONS_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_dimensions.scad"


def test_pi_dimensions_defines_hole_spacing_constant() -> None:
    """Shared Pi mounting hole spacing should be defined once."""

    source = DIMENSIONS_PATH.read_text(encoding="utf-8")
    assert "pi_hole_spacing" in source, "pi_dimensions.scad should declare pi_hole_spacing"
    assert "[58, 49]" in source, "Pi mounting hole spacing should remain 58×49 mm"


def test_pi_carrier_uses_shared_hole_spacing() -> None:
    """pi_carrier.scad should consume the shared Pi hole spacing constant."""

    source = PI_CARRIER_PATH.read_text(encoding="utf-8")
    assert "pi_dimensions.scad" in source, "pi_carrier.scad should include pi_dimensions.scad"
    assert "pi_hole_spacing" in source, "pi_carrier.scad should derive spacing from pi_hole_spacing"


def test_pi_carrier_stack_column_spacing_uses_shared_constant() -> None:
    """column_spacing defaults should reuse the Pi hole spacing constant."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert (
        "pi_hole_spacing" in source
    ), "pi_carrier_stack.scad should default column_spacing to pi_hole_spacing"
    assert "[58, 49]" not in source, "column_spacing literals drift from the shared constant"


def test_pi_carrier_stack_alignment_guard_reuses_shared_spacing() -> None:
    """Alignment guard should mirror the shared Pi hole spacing constant."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert (
        "expected_column_spacing = pi_hole_spacing" in source
    ), "Alignment guard should derive from pi_hole_spacing instead of duplicating literals"


def test_fan_wall_column_spacing_uses_shared_constant() -> None:
    """fan_wall.scad column tabs must align with the shared Pi hole spacing."""

    source = FAN_WALL_PATH.read_text(encoding="utf-8")
    assert "pi_hole_spacing" in source, "fan_wall.scad should reuse the pi_hole_spacing constant"
    assert "[58, 49]" not in source, "fan_wall column spacing should reference the shared constant"


def test_pi_carrier_stack_imports_pi_carrier_module() -> None:
    """pi_carrier_stack should reuse the base module instead of cubes."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert "pi_carrier.scad" in source, "pi_carrier_stack should import pi_carrier.scad"
    assert re.search(r"\bpi_carrier\s*\(", source), "pi_carrier_stack should call pi_carrier()"


def test_pi_carrier_stack_mentions_stl_output_location() -> None:
    """The SCAD file should document where generated STL files are emitted."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert (
        "stl/pi_cluster" in source
    ), "Add a comment pointing to the STL output directory for discoverability"
