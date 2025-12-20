from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
OPENSCAD = shutil.which("openscad")


@pytest.mark.skipif(OPENSCAD is None, reason="openscad binary not available")
def test_pi_carrier_stack_cli_renders_without_console_errors(tmp_path: Path) -> None:
    output = tmp_path / "pi_carrier_stack.stl"
    result = subprocess.run(
        [
            "openscad",
            "-o",
            str(output),
            "--export-format",
            "binstl",
            str(SCAD_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = (result.stdout or "") + (result.stderr or "")

    assert result.returncode == 0, f"OpenSCAD render failed with output:\n{combined_output}"
    for term in (
        "undefined operation",
        "Unable to convert translate",
        "max() parameter could not be converted",
        "min() parameter could not be converted",
    ):
        assert term not in combined_output


@pytest.mark.skipif(OPENSCAD is None, reason="openscad binary not available")
def test_pi_carrier_stack_emits_geometry_report(tmp_path: Path) -> None:
    output = tmp_path / "pi_carrier_stack_geometry.stl"
    result = subprocess.run(
        [
            "openscad",
            "-D",
            "emit_geometry_report=true",
            "-D",
            "export_part=\"carrier_level\"",
            "-o",
            str(output),
            str(SCAD_PATH),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = (result.stdout or "") + (result.stderr or "")
    geometry_line = next(
        (line for line in combined_output.splitlines() if "pi_carrier_geometry" in line),
        "",
    )

    assert result.returncode == 0, f"OpenSCAD render failed with output:\n{combined_output}"
    assert geometry_line, f"OpenSCAD did not emit geometry report:\n{combined_output}"

    def extract_float(label: str) -> float:
        match = re.search(fr"{label}\\s*=\\s*([^,]+)", geometry_line)
        assert match, f"{label} missing from geometry report: {geometry_line}"
        return float(match.group(1))

    plate_len = extract_float("plate_len")
    plate_wid = extract_float("plate_wid")
    plate_thickness = extract_float("plate_thickness")
    stack_mount_inset = extract_float("stack_mount_inset")
    stack_pocket_d = extract_float("stack_pocket_d")
    stack_pocket_depth = extract_float("stack_pocket_depth")

    positions_match = re.search(
        r"stack_mount_positions\s*=\s*(\[[^\]]+\])", geometry_line
    )
    assert positions_match, f"stack_mount_positions missing from geometry report: {geometry_line}"
    stack_mount_positions = ast.literal_eval(positions_match.group(1))

    assert len(stack_mount_positions) >= 4, "Expected at least four stack mounts"
    xs = sorted({round(pos[0], 3) for pos in stack_mount_positions})
    ys = sorted({round(pos[1], 3) for pos in stack_mount_positions})

    assert len(xs) == 2 and len(ys) == 2, "Stack mounts should form a rectangular grid"

    min_clearance_x = min(min(xs), plate_len - max(xs))
    min_clearance_y = min(min(ys), plate_wid - max(ys))
    assert min_clearance_x > stack_mount_inset / 2
    assert min_clearance_y > stack_mount_inset / 2

    for x, y in stack_mount_positions:
        assert 0 < x < plate_len
        assert 0 < y < plate_wid

    assert stack_pocket_depth < plate_thickness / 2
    assert stack_mount_inset > stack_pocket_d
