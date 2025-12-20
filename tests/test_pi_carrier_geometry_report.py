"""Regression tests for `pi_carrier.scad` geometry echoes."""

from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import run_openscad_and_capture_echoes

SCAD_ROOT = Path("cad/pi_cluster")
OPENSCAD = shutil.which("openscad")
EPSILON = 1e-3


def _run_geometry(defs: list[str], out_path: Path):
    scad_path = SCAD_ROOT / "pi_carrier.scad"
    return run_openscad_and_capture_echoes(scad_path, defs, out_path)


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_geometry_report_invariants(tmp_path: Path) -> None:
    base_out = tmp_path / "pi_carrier_base.stl"
    base_result = _run_geometry(["emit_geometry_report=true"], base_out)
    base_geo = base_result.last_for_label("pi_carrier_geometry").values

    assert base_geo["include_stack_mounts"] is False
    assert base_geo["plate_outer_bounds_min"] == [0, 0]
    assert math.isclose(
        base_geo["plate_outer_bounds_max"][0], base_geo["plate_len"], abs_tol=EPSILON
    )
    assert math.isclose(
        base_geo["plate_outer_bounds_max"][1], base_geo["plate_wid"], abs_tol=EPSILON
    )
    assert base_geo.get("stack_mount_positions", []) == []

    preview_out = tmp_path / "pi_carrier_preview.stl"
    preview_defs = ["emit_geometry_report=true", "preview_stack_mounts=true"]
    preview_result = _run_geometry(preview_defs, preview_out)
    preview_geo = preview_result.last_for_label("pi_carrier_geometry").values

    assert preview_geo["include_stack_mounts"] is True
    stack_mount_positions = preview_geo["stack_mount_positions"]
    assert len(stack_mount_positions) == 4

    min_x = min(pos[0] for pos in stack_mount_positions)
    max_x = max(pos[0] for pos in stack_mount_positions)
    min_y = min(pos[1] for pos in stack_mount_positions)
    max_y = max(pos[1] for pos in stack_mount_positions)

    left_inset = min_x
    right_inset = preview_geo["plate_len"] - max_x
    bottom_inset = min_y
    top_inset = preview_geo["plate_wid"] - max_y

    assert math.isclose(left_inset, right_inset, abs_tol=EPSILON)
    assert math.isclose(bottom_inset, top_inset, abs_tol=EPSILON)
    assert math.isclose(left_inset, bottom_inset, abs_tol=EPSILON)

    assert "stack_mount_margin_center" in preview_geo
    assert math.isclose(preview_geo["stack_mount_margin_center"], left_inset, abs_tol=EPSILON)
    assert "stack_mount_margin_pocket_edge" in preview_geo
    assert math.isclose(
        preview_geo["stack_mount_margin_pocket_edge"],
        preview_geo["stack_mount_margin_center"] - preview_geo["stack_pocket_d"] / 2,
        abs_tol=EPSILON,
    )

    assert math.isclose(base_geo["plate_len"], preview_geo["plate_len"], abs_tol=EPSILON)
    assert math.isclose(base_geo["plate_wid"], preview_geo["plate_wid"], abs_tol=EPSILON)

    assert "plate_len_stack_off" in base_geo
    assert "plate_wid_stack_off" in base_geo
    assert math.isclose(base_geo["plate_len_stack_off"], base_geo["plate_len"], abs_tol=EPSILON)
    assert math.isclose(base_geo["plate_wid_stack_off"], base_geo["plate_wid"], abs_tol=EPSILON)

    assert "plate_len_stack_off" in preview_geo
    assert "plate_wid_stack_off" in preview_geo
    assert math.isclose(
        preview_geo["plate_len_stack_off"], preview_geo["plate_len"], abs_tol=EPSILON
    )
    assert math.isclose(
        preview_geo["plate_wid_stack_off"], preview_geo["plate_wid"], abs_tol=EPSILON
    )
