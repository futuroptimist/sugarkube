"""Regression coverage for stack clamp holes and pockets."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCAD_PATH = Path("cad/pi_cluster/pi_carrier_stack.scad")
BASE_CARRIER = Path("cad/pi_cluster/pi_carrier.scad")
OPENSCAD = shutil.which("openscad")


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_stack_carrier_echoes_stack_mount_settings(tmp_path: Path) -> None:
    """Rendering the stack carrier should surface stack mount configuration."""

    output = tmp_path / "carrier_level.stl"
    result = subprocess.run(
        [
            OPENSCAD,
            "-o",
            str(output),
            "-D",
            'export_part="carrier_level"',
            "-D",
            'standoff_mode="heatset"',
            str(SCAD_PATH),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stderr = result.stderr
    assert "stack_mounts_enabled" in stderr
    assert "include_stack_mounts = true" in stderr
    assert "stack_pocket_d = 9" in stderr


@pytest.mark.skipif(not OPENSCAD, reason="OpenSCAD is not available")
def test_stack_carrier_geometry_differs_from_base(tmp_path: Path) -> None:
    """Stack-ready carrier should produce a materially different mesh than the base plate."""

    stack_output = tmp_path / "stack.stl"
    base_output = tmp_path / "base.stl"

    subprocess.run(
        [
            OPENSCAD,
            "-o",
            str(stack_output),
            "-D",
            'export_part="carrier_level"',
            str(SCAD_PATH),
        ],
        check=True,
        capture_output=True,
    )

    subprocess.run(
        [
            OPENSCAD,
            "-o",
            str(base_output),
            str(BASE_CARRIER),
        ],
        check=True,
        capture_output=True,
    )

    assert stack_output.exists()
    assert base_output.exists()
    assert stack_output.stat().st_size > base_output.stat().st_size
