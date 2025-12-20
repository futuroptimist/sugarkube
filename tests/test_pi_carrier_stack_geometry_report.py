from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import (
    last_echo_with_label,
    parse_echo_key_values,
    run_openscad_collect_echoes,
)

STACK_SCAD = Path("cad/pi_cluster/pi_carrier_stack.scad")
CARRIER_SCAD = Path("cad/pi_cluster/pi_carrier.scad")
OPENSCAD = shutil.which("openscad")
EPSILON = 1e-3


def _run_stack_geometry(tmp_path: Path) -> dict[str, dict[str, object]]:
    echoes = run_openscad_collect_echoes(
        STACK_SCAD,
        tmp_path,
        {
            "export_part": "\"carrier_level\"",
            "emit_dimension_report": True,
            "emit_geometry_report": True,
        },
    )

    return {
        "dimensions": parse_echo_key_values(
            last_echo_with_label(echoes, "pi_carrier_stack"), "pi_carrier_stack"
        ),
        "stack_mounts": parse_echo_key_values(
            last_echo_with_label(echoes, "stack_mounts_enabled"), "stack_mounts_enabled"
        ),
        "geometry": parse_echo_key_values(
            last_echo_with_label(echoes, "pi_carrier_geometry"), "pi_carrier_geometry"
        ),
    }


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_stack_wrapper_forwards_geometry_and_dimension_reports(tmp_path: Path) -> None:
    stack_reports = _run_stack_geometry(tmp_path)

    dimensions = stack_reports["dimensions"]
    assert all(
        key in dimensions for key in {"levels", "fan_size", "column_spacing", "stack_height"}
    )
    assert dimensions.get("export_part") == "carrier_level"

    stack_mounts = stack_reports["stack_mounts"]
    assert stack_mounts.get("include_stack_mounts") is True
    assert len(stack_mounts.get("stack_mount_positions", [])) == 4

    geometry = stack_reports["geometry"]
    assert geometry.get("include_stack_mounts") is True
    assert len(geometry.get("stack_mount_positions", [])) == 4


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_stack_embedded_carrier_matches_previewed_carrier(tmp_path: Path) -> None:
    stack_reports = _run_stack_geometry(tmp_path)

    carrier_echoes = run_openscad_collect_echoes(
        CARRIER_SCAD,
        tmp_path,
        {"emit_geometry_report": True, "preview_stack_mounts": True},
    )
    carrier_geometry = parse_echo_key_values(
        last_echo_with_label(carrier_echoes, "pi_carrier_geometry"), "pi_carrier_geometry"
    )

    stack_geometry = stack_reports["geometry"]
    assert stack_geometry["include_stack_mounts"] is True
    assert len(stack_geometry.get("stack_mount_positions", [])) == 4

    assert stack_geometry["plate_len"] == pytest.approx(
        carrier_geometry["plate_len"], abs=EPSILON
    )
    assert stack_geometry["plate_wid"] == pytest.approx(
        carrier_geometry["plate_wid"], abs=EPSILON
    )
