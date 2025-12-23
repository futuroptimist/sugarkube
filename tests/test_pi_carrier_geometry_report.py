from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import find_last_echo, parse_echo_line, run_openscad

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier.scad"
OPENSCAD = shutil.which("openscad")
EPSILON = 1e-3


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_geometry_report_invariants() -> None:
    echoes_off = run_openscad(
        SCAD_PATH,
        {"emit_geometry_report": True},
        openscad_path=str(OPENSCAD),
    )
    off_line = find_last_echo(echoes_off, "pi_carrier_geometry")
    _, geometry_off = parse_echo_line(off_line)

    assert geometry_off["include_stack_mounts"] is False
    assert geometry_off["plate_outer_bounds_min"] == [0, 0]

    plate_len_off = geometry_off["plate_len"]
    plate_wid_off = geometry_off["plate_wid"]
    assert geometry_off["plate_outer_bounds_max"] == pytest.approx(
        [plate_len_off, plate_wid_off],
        abs=EPSILON,
    )
    assert geometry_off.get("stack_mount_positions", []) == []

    echoes_on = run_openscad(
        SCAD_PATH,
        {"emit_geometry_report": True, "preview_stack_mounts": True},
        openscad_path=str(OPENSCAD),
    )
    on_line = find_last_echo(echoes_on, "pi_carrier_geometry")
    _, geometry_on = parse_echo_line(on_line)

    assert geometry_on["include_stack_mounts"] is True

    positions = geometry_on["stack_mount_positions"]
    assert len(positions) == 4
    xs = [pos[0] for pos in positions]
    ys = [pos[1] for pos in positions]
    plate_len_on = geometry_on["plate_len"]
    plate_wid_on = geometry_on["plate_wid"]

    left = min(xs)
    right = plate_len_on - max(xs)
    bottom = min(ys)
    top = plate_wid_on - max(ys)

    assert left == pytest.approx(right, abs=EPSILON)
    assert bottom == pytest.approx(top, abs=EPSILON)
    assert left == pytest.approx(bottom, abs=EPSILON)

    margin_center = geometry_on["stack_mount_margin_center"]
    assert margin_center == pytest.approx(left, abs=EPSILON)

    pocket_edge = geometry_on["stack_mount_margin_pocket_edge"]
    assert pocket_edge == pytest.approx(
        margin_center - geometry_on["stack_pocket_d"] / 2,
        abs=EPSILON,
    )
    assert pocket_edge > 0

    expected_inset = max(
        geometry_on["corner_radius"]
        + geometry_on["stack_pocket_d"] / 2
        + 0.5,
        max(0, geometry_on["edge_margin"] - 3),
    )
    assert geometry_on["stack_mount_inset"] == pytest.approx(expected_inset, abs=EPSILON)
    assert geometry_on["stack_bolt_d"] == pytest.approx(3.4, abs=EPSILON)

    assert plate_len_on == pytest.approx(plate_len_off, abs=EPSILON)
    assert plate_wid_on == pytest.approx(plate_wid_off, abs=EPSILON)

    assert geometry_on["plate_len_stack_off"] == pytest.approx(plate_len_on, abs=EPSILON)
    assert geometry_on["plate_wid_stack_off"] == pytest.approx(plate_wid_on, abs=EPSILON)
