from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
PI_CARRIER_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier.scad"
FAN_WALL_PATH = REPO_ROOT / "cad" / "pi_cluster" / "fan_wall.scad"
DIMENSIONS_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_dimensions.scad"
STACK_POST_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_stack_post.scad"
STACK_ADAPTER_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_stack_fan_adapter.scad"


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


def test_pi_carrier_stack_includes_local_dependencies() -> None:
    """Use explicit relative includes so OpenSCAD resolves dependencies reliably."""

    source = SCAD_PATH.read_text(encoding="utf-8")

    assert "include <./pi_dimensions.scad>" in source
    assert "include <./pi_carrier.scad>" in source
    assert "pi_stack_post.scad" in source
    assert "pi_stack_fan_adapter.scad" in source
    assert "use <./fan_wall.scad>" in source


def test_stack_mount_hook_present() -> None:
    """Stack carriers should expose the locating pocket hooks."""

    source = PI_CARRIER_PATH.read_text(encoding="utf-8")
    assert "include_stack_mounts" in source
    assert "stack_mount_positions" in source
    assert "stack_pocket_depth" in source


def test_stack_carrier_uses_thicker_plate_for_pockets() -> None:
    """Stack renders should thicken the carrier plate so symmetric pockets do not overlap."""

    source = SCAD_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"stack_plate_thickness\s*=\s*is_undef\(stack_plate_thickness\)\s*\?\s*3\.0", source
    )
    assert (
        "plate_thickness = is_undef(plate_thickness) ? stack_plate_thickness : plate_thickness"
        in source
    )


def test_stack_components_exist() -> None:
    """Modular stack parts should live alongside the carrier source."""

    assert STACK_POST_PATH.exists(), "Add cad/pi_cluster/pi_stack_post.scad for printed spacers"
    assert STACK_ADAPTER_PATH.exists(), "Add cad/pi_cluster/pi_stack_fan_adapter.scad for fan clamp"


def test_stack_mount_pockets_on_both_faces() -> None:
    """Carrier pockets should be cut from the top and bottom faces for symmetry."""

    source = PI_CARRIER_PATH.read_text(encoding="utf-8")
    assert "plate_thickness - stack_pocket_depth" in source
    assert re.search(
        r"mount_x, mount_y, -0\.01\]\)\s*cylinder\(h = stack_pocket_depth \+ 0\.02",
        source,
    ), "Bottom pocket should mirror the top pocket when include_stack_mounts=true"


def test_stack_post_boss_clearance() -> None:
    """Posts should key into pockets with a documented clearance."""

    source = STACK_POST_PATH.read_text(encoding="utf-8")
    assert "boss_fit_clearance" in source
    assert "boss_d = stack_pocket_d - boss_fit_clearance" in source


def test_fan_adapter_interfaces_align_with_stack_mounts() -> None:
    """Fan adapter interfaces should follow the fan-side stack mount Y positions."""

    source = STACK_ADAPTER_PATH.read_text(encoding="utf-8")
    assert "fan_side_positions" in source
    assert "interface_offsets = [for (pos = fan_side_positions) pos[1]]" in source
