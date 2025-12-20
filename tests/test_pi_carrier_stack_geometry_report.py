"""Validate geometry echoes from `pi_carrier_stack.scad`."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import run_openscad_and_capture_echoes

SCAD_ROOT = Path("cad/pi_cluster")
OPENSCAD = shutil.which("openscad")
EPSILON = 1e-3


def _run_stack(defs: list[str], out_path: Path):
    scad_path = SCAD_ROOT / "pi_carrier_stack.scad"
    return run_openscad_and_capture_echoes(scad_path, defs, out_path)


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_stack_forwards_geometry(tmp_path: Path) -> None:
    stack_defs = [
        'export_part="carrier_level"',
        "emit_dimension_report=true",
        "emit_geometry_report=true",
    ]
    stack_out = tmp_path / "pi_carrier_stack_level.stl"
    stack_result = _run_stack(stack_defs, stack_out)

    stack_dimension = stack_result.last_for_label("pi_carrier_stack").values
    for key in ["levels", "fan_size", "column_spacing", "stack_height", "export_part"]:
        assert key in stack_dimension

    stack_mounts = stack_result.last_for_label("stack_mounts_enabled").values
    assert stack_mounts["include_stack_mounts"] is True
    assert len(stack_mounts["stack_mount_positions"]) == 4

    carrier_geo = stack_result.last_for_label("pi_carrier_geometry").values
    assert carrier_geo["include_stack_mounts"] is True
    assert len(carrier_geo["stack_mount_positions"]) == 4

    base_preview_out = tmp_path / "pi_carrier_preview_compare.stl"
    base_preview = run_openscad_and_capture_echoes(
        SCAD_ROOT / "pi_carrier.scad",
        ["emit_geometry_report=true", "preview_stack_mounts=true"],
        base_preview_out,
    ).last_for_label("pi_carrier_geometry").values

    assert math.isclose(
        carrier_geo["plate_len"], base_preview["plate_len"], abs_tol=EPSILON
    )
    assert math.isclose(
        carrier_geo["plate_wid"], base_preview["plate_wid"], abs_tol=EPSILON
    )
