from __future__ import annotations
import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import (
    last_echo_with_label,
    parse_echo_key_values,
    run_openscad_collect_echoes,
)

SCAD_PATH = Path("cad/pi_cluster/pi_carrier.scad")
OPENSCAD = shutil.which("openscad")
EPSILON = 1e-3


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_geometry_reports_bounds_and_invariants(tmp_path: Path) -> None:
    base_echoes = run_openscad_collect_echoes(
        SCAD_PATH,
        tmp_path,
        {"emit_geometry_report": True},
    )
    base_geometry = parse_echo_key_values(
        last_echo_with_label(base_echoes, "pi_carrier_geometry"), "pi_carrier_geometry"
    )

    assert base_geometry["include_stack_mounts"] is False
    assert base_geometry["plate_outer_bounds_min"] == [0, 0]
    assert base_geometry["plate_outer_bounds_max"] == pytest.approx(
        [base_geometry["plate_len"], base_geometry["plate_wid"]], abs=EPSILON
    )
    assert base_geometry.get("stack_mount_positions", []) in ([],)

    preview_echoes = run_openscad_collect_echoes(
        SCAD_PATH,
        tmp_path,
        {"emit_geometry_report": True, "preview_stack_mounts": True},
    )
    preview_geometry = parse_echo_key_values(
        last_echo_with_label(preview_echoes, "pi_carrier_geometry"), "pi_carrier_geometry"
    )

    assert preview_geometry["include_stack_mounts"] is True

    mount_positions = preview_geometry.get("stack_mount_positions", [])
    assert len(mount_positions) == 4

    xs = [pos[0] for pos in mount_positions]
    ys = [pos[1] for pos in mount_positions]
    left_inset = min(xs)
    right_inset = preview_geometry["plate_len"] - max(xs)
    bottom_inset = min(ys)
    top_inset = preview_geometry["plate_wid"] - max(ys)

    assert left_inset == pytest.approx(right_inset, abs=EPSILON)
    assert bottom_inset == pytest.approx(top_inset, abs=EPSILON)
    assert left_inset == pytest.approx(bottom_inset, abs=EPSILON)

    assert preview_geometry["stack_mount_margin_center"] == pytest.approx(
        left_inset, abs=EPSILON
    )
    assert preview_geometry["stack_mount_margin_pocket_edge"] == pytest.approx(
        preview_geometry["stack_mount_margin_center"]
        - preview_geometry["stack_pocket_d"] / 2,
        abs=EPSILON,
    )

    assert base_geometry["plate_len"] == pytest.approx(
        preview_geometry["plate_len"], abs=EPSILON
    )
    assert base_geometry["plate_wid"] == pytest.approx(
        preview_geometry["plate_wid"], abs=EPSILON
    )

    assert base_geometry["plate_len_stack_off"] == pytest.approx(
        base_geometry["plate_len"], abs=EPSILON
    )
    assert base_geometry["plate_wid_stack_off"] == pytest.approx(
        base_geometry["plate_wid"], abs=EPSILON
    )
