from __future__ import annotations

import math
from pathlib import Path

import pytest

from tests.openscad_echo import OPENSCAD, run_openscad_with_defs

SCAD_PATH = Path("cad/pi_cluster/pi_carrier.scad")
EPSILON = 1e-3


def _render_geometry(tmp_path: Path, defs: list[str]):
    result = run_openscad_with_defs(
        SCAD_PATH,
        defs + ["emit_geometry_report=true"],
        tmp_path / "pi_carrier.stl",
    )
    geometry = result.last_echo_dict("pi_carrier_geometry")
    assert geometry, "Geometry report was not emitted"
    return geometry


def _assert_close(a: float, b: float, *, msg: str) -> None:
    assert math.isclose(a, b, rel_tol=0, abs_tol=EPSILON), msg


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_geometry_report_covers_stack_preview(tmp_path: Path) -> None:
    geometry_no_stack = _render_geometry(tmp_path, defs=[])

    assert geometry_no_stack["include_stack_mounts"] is False
    assert geometry_no_stack["plate_outer_bounds_min"] == [0, 0]
    _assert_close(
        geometry_no_stack["plate_outer_bounds_max"][0],
        geometry_no_stack["plate_len"],
        msg="plate_outer_bounds_max.x should match plate_len",
    )
    _assert_close(
        geometry_no_stack["plate_outer_bounds_max"][1],
        geometry_no_stack["plate_wid"],
        msg="plate_outer_bounds_max.y should match plate_wid",
    )
    assert geometry_no_stack["stack_mount_positions"] == []

    geometry_preview = _render_geometry(tmp_path, defs=["preview_stack_mounts=true"])

    assert geometry_preview["include_stack_mounts"] is True
    stack_mount_positions = geometry_preview["stack_mount_positions"]
    assert len(stack_mount_positions) == 4

    xs = [pos[0] for pos in stack_mount_positions]
    ys = [pos[1] for pos in stack_mount_positions]
    left = min(xs)
    right = geometry_preview["plate_len"] - max(xs)
    bottom = min(ys)
    top = geometry_preview["plate_wid"] - max(ys)

    _assert_close(left, right, msg="Stack mount X insets should match")
    _assert_close(bottom, top, msg="Stack mount Y insets should match")
    _assert_close(left, bottom, msg="Stack mount inset should be uniform")

    _assert_close(
        geometry_preview["stack_mount_margin_center"],
        left,
        msg="stack_mount_margin_center should reflect inset",
    )
    _assert_close(
        geometry_preview["stack_mount_margin_pocket_edge"],
        geometry_preview["stack_mount_margin_center"]
        - geometry_preview["stack_pocket_d"] / 2,
        msg="Pocket edge margin should offset from center",
    )

    _assert_close(
        geometry_preview["plate_len"],
        geometry_no_stack["plate_len"],
        msg="plate_len should be invariant to stack mounts",
    )
    _assert_close(
        geometry_preview["plate_wid"],
        geometry_no_stack["plate_wid"],
        msg="plate_wid should be invariant to stack mounts",
    )

    _assert_close(
        geometry_preview["plate_len_stack_off"],
        geometry_preview["plate_len"],
        msg="plate_len_stack_off should mirror plate_len",
    )
    _assert_close(
        geometry_preview["plate_wid_stack_off"],
        geometry_preview["plate_wid"],
        msg="plate_wid_stack_off should mirror plate_wid",
    )
