from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import (
    find_last_echo,
    parse_echo_line,
    run_openscad,
    run_openscad_with_output,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
CARRIER_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier.scad"
OPENSCAD = shutil.which("openscad")
EPSILON = 1e-3


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_pi_carrier_stack_reports_geometry() -> None:
    echoes = run_openscad(
        STACK_SCAD,
        {
            "export_part": "carrier_level",
            "emit_dimension_report": True,
            "emit_geometry_report": True,
        },
        openscad_path=str(OPENSCAD),
    )

    stack_line = find_last_echo(echoes, "pi_carrier_stack")
    _, stack_dimensions = parse_echo_line(stack_line)
    for key in ["levels", "fan_size", "column_spacing", "stack_height", "export_part"]:
        assert key in stack_dimensions
    assert stack_dimensions["stack_bolt_d"] == pytest.approx(3.4, abs=EPSILON)

    stack_mounts_line = find_last_echo(echoes, "stack_mounts_enabled")
    _, stack_mounts = parse_echo_line(stack_mounts_line)
    assert stack_mounts["include_stack_mounts"] is True
    assert len(stack_mounts["stack_mount_positions"]) == 4

    geometry_line = find_last_echo(echoes, "pi_carrier_geometry")
    _, geometry = parse_echo_line(geometry_line)

    assert geometry["include_stack_mounts"] is True
    assert len(geometry["stack_mount_positions"]) == 4
    assert geometry["stack_bolt_d"] == pytest.approx(3.4, abs=EPSILON)
    assert geometry["stack_mount_margin_pocket_edge"] > 0

    carrier_echoes = run_openscad(
        CARRIER_SCAD,
        {"emit_geometry_report": True, "preview_stack_mounts": True},
        openscad_path=str(OPENSCAD),
    )
    carrier_geometry_line = find_last_echo(carrier_echoes, "pi_carrier_geometry")
    _, standalone_geometry = parse_echo_line(carrier_geometry_line)

    assert geometry["plate_len"] == pytest.approx(
        standalone_geometry["plate_len"],
        abs=EPSILON,
    )
    assert geometry["plate_wid"] == pytest.approx(
        standalone_geometry["plate_wid"],
        abs=EPSILON,
    )


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_carrier_level_geometry_bounds_and_mounts() -> None:
    stdout, stderr = run_openscad_with_output(
        STACK_SCAD,
        {
            "export_part": "carrier_level",
            "emit_dimension_report": True,
            "emit_geometry_report": True,
        },
        openscad_path=str(OPENSCAD),
    )

    echoes = [line for line in stderr.splitlines() if "ECHO:" in line]

    stack_line = find_last_echo(echoes, "pi_carrier_stack")
    _, stack_dimensions = parse_echo_line(stack_line)

    for key in ["levels", "fan_size", "column_spacing", "stack_height", "export_part"]:
        assert key in stack_dimensions

    geometry_line = find_last_echo(echoes, "pi_carrier_geometry")
    _, geometry = parse_echo_line(geometry_line)

    assert geometry["include_stack_mounts"] is True
    assert len(geometry["stack_mount_positions"]) == 4

    assert geometry["plate_outer_bounds_min"] == pytest.approx([0, 0], abs=EPSILON)
    assert geometry["plate_outer_bounds_max"] == pytest.approx(
        [geometry["plate_len"], geometry["plate_wid"]],
        abs=EPSILON,
    )

    for warning in ["WARNING: Ignoring unknown variable", "was assigned"]:
        assert warning not in stderr

    assert not stdout.strip()
