"""Regression tests for stack mount placement and logging."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
BASE_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier.scad"


pytestmark = pytest.mark.skipif(
    shutil.which("openscad") is None, reason="openscad binary not available"
)


def _render(scad: Path, output: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "openscad",
            "-o",
            str(output),
            "--export-format",
            "binstl",
            *extra_args,
            str(scad),
        ],
        capture_output=True,
        text=True,
    )


def test_carrier_level_echoes_stack_mount_settings(tmp_path: Path) -> None:
    """Rendering the carrier level should log stack mount parameters for guardrails."""

    output_path = tmp_path / "pi_carrier_stack_carrier_level_heatset.stl"
    result = _render(
        STACK_SCAD,
        output_path,
        "-D",
        'export_part="carrier_level"',
        "-D",
        'standoff_mode="heatset"',
    )

    assert result.returncode == 0, result.stderr
    log = result.stdout + result.stderr
    assert "stack_mounts_enabled" in log
    assert "include_stack_mounts" in log
    assert "stack_mount_positions" in log
    assert output_path.exists()


def test_stack_carrier_geometry_exceeds_flat_carrier(tmp_path: Path) -> None:
    """The stack-ready carrier should be noticeably larger than the flat plate."""

    base_output = tmp_path / "pi_carrier_heatset.stl"
    base = _render(
        BASE_SCAD,
        base_output,
        "-D",
        'standoff_mode="heatset"',
    )
    assert base.returncode == 0, base.stderr

    stack_output = tmp_path / "pi_carrier_stack_mounts_heatset.stl"
    stack = _render(
        BASE_SCAD,
        stack_output,
        "-D",
        "include_stack_mounts=true",
        "-D",
        'standoff_mode="heatset"',
        "-D",
        "plate_thickness=3",
        "-D",
        "stack_edge_margin=15",
        "-D",
        "stack_pocket_d=9",
        "-D",
        "stack_pocket_depth=1.2",
    )
    assert stack.returncode == 0, stack.stderr

    assert stack_output.stat().st_size > base_output.stat().st_size


def test_stack_wrapper_renders_without_warnings(tmp_path: Path) -> None:
    """Opening the stack wrapper directly should behave like CI renders."""

    output_path = tmp_path / "pi_carrier_stack_default.stl"
    result = _render(STACK_SCAD, output_path)

    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "ERROR:" not in log
    assert "WARNING: Ignoring unknown variable" not in log
    assert output_path.exists()
