"""Ensure pi cluster CAD modules expose dimension echoes for regression tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCAD_ROOT = Path("cad/pi_cluster")
OPENSCAD = shutil.which("openscad")


@pytest.mark.parametrize(
    ("filename", "label"),
    [
        ("pi_carrier_column.scad", '"pi_carrier_column"'),
        ("fan_wall.scad", '"fan_wall"'),
        ("pi_carrier_stack.scad", '"pi_carrier_stack"'),
    ],
)
def test_dimension_report_echo_is_declared(filename: str, label: str) -> None:
    """Each SCAD entry point should expose an echo for dimension reporting."""

    source = (SCAD_ROOT / filename).read_text(encoding="utf-8")
    assert "emit_dimension_report" in source, "dimension report toggle missing"
    assert label in source, f"{filename} should include a dimension echo"


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
@pytest.mark.parametrize(
    ("filename", "expected_keys", "extra_defs"),
    [
        (
            "pi_carrier_column.scad",
            ["levels", "z_gap_clear", "column_height", "column_od", "column_mode"],
            [],
        ),
        (
            "fan_wall.scad",
            ["fan_size", "hole_spacing", "column_spacing", "levels", "include_bosses"],
            [],
        ),
        (
            "pi_carrier_stack.scad",
            ["levels", "fan_size", "column_mode", "column_spacing", "stack_height"],
            [],
        ),
    ],
)
def test_dimension_report_echo_outputs_expected_keys(
    tmp_path, filename: str, expected_keys: list[str], extra_defs: list[str]
) -> None:
    """Running the SCAD file with emits should surface the expected echo keys."""

    out_file = tmp_path / f"{Path(filename).stem}.stl"
    cmd = ["openscad", "-o", str(out_file)]
    for definition in ["emit_dimension_report=true", *extra_defs]:
        cmd.extend(["-D", definition])
    cmd.append(str(SCAD_ROOT / filename))

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    echoes = [line for line in result.stderr.splitlines() if "ECHO:" in line]
    assert echoes, "OpenSCAD did not emit any dimension report"

    last_echo = echoes[-1]
    for key in expected_keys:
        assert f"{key} =" in last_echo, f"{key} missing from dimension report"
