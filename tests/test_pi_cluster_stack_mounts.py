from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
CARRIER_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier.scad"


@pytest.mark.skipif(shutil.which("openscad") is None, reason="openscad binary not available")
def test_stack_carrier_emits_stack_mount_echo(tmp_path: Path) -> None:
    """Carrier-level renders should log the stack mount configuration."""

    stack_output = tmp_path / "pi_carrier_stack_carrier_level_heatset.stl"
    result = subprocess.run(
        [
            "openscad",
            "-o",
            str(stack_output),
            "--export-format",
            "binstl",
            "-D",
            'export_part="carrier_level"',
            "-D",
            'standoff_mode="heatset"',
            str(STACK_SCAD),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    log = (result.stdout + result.stderr).lower()
    assert "stack_mounts_enabled" in log
    assert "include_stack_mounts = true" in log
    assert "stack_pocket_d" in log
    assert stack_output.exists(), "openscad should emit the carrier-level STL"

    base_output = tmp_path / "pi_carrier_heatset.stl"
    base_result = subprocess.run(
        [
            "openscad",
            "-o",
            str(base_output),
            "--export-format",
            "binstl",
            "-D",
            'standoff_mode="heatset"',
            str(CARRIER_SCAD),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert base_result.stdout is not None
    assert base_output.exists(), "openscad should emit the standalone carrier"
    assert (
        stack_output.stat().st_size > base_output.stat().st_size
    ), "Stack plate should be thicker and include clamp features"
