from __future__ import annotations

from pathlib import Path

import pytest

from tests.openscad_echo import OPENSCAD, run_openscad_with_defs

STACK_SCAD_PATH = Path("cad/pi_cluster/pi_carrier_stack.scad")
CARRIER_SCAD_PATH = Path("cad/pi_cluster/pi_carrier.scad")


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_stack_relays_geometry_and_dimension_reports(tmp_path: Path) -> None:
    stack_result = run_openscad_with_defs(
        STACK_SCAD_PATH,
        [
            "export_part=\"carrier_level\"",
            "emit_dimension_report=true",
            "emit_geometry_report=true",
        ],
        tmp_path / "pi_carrier_stack.stl",
    )

    dimension_report = stack_result.last_echo_dict("pi_carrier_stack")
    for key in ["levels", "fan_size", "column_spacing", "stack_height", "export_part"]:
        assert key in dimension_report, f"{key} missing from pi_carrier_stack report"

    stack_mounts = stack_result.last_echo_dict("stack_mounts_enabled")
    assert stack_mounts["include_stack_mounts"] is True
    assert len(stack_mounts["stack_mount_positions"]) == 4

    carrier_geometry = stack_result.last_echo_dict("pi_carrier_geometry")
    assert carrier_geometry["include_stack_mounts"] is True
    assert len(carrier_geometry["stack_mount_positions"]) == 4

    preview_result = run_openscad_with_defs(
        CARRIER_SCAD_PATH,
        ["preview_stack_mounts=true", "emit_geometry_report=true"],
        tmp_path / "pi_carrier_preview.stl",
    )
    preview_geometry = preview_result.last_echo_dict("pi_carrier_geometry")

    assert preview_geometry["include_stack_mounts"] is True
    assert len(preview_geometry["stack_mount_positions"]) == 4

    assert carrier_geometry["plate_len"] == pytest.approx(preview_geometry["plate_len"])
    assert carrier_geometry["plate_wid"] == pytest.approx(preview_geometry["plate_wid"])
