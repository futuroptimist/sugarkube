from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"

OPENSCAD = shutil.which("openscad")
FAILURE_SUBSTRINGS = [
    "undefined operation",
    "Unable to convert translate",
    "max() parameter could not be converted",
    "min() parameter could not be converted",
]


@pytest.mark.skipif(not OPENSCAD, reason="openscad binary not available")
def test_pi_carrier_stack_cli_renders_without_console_errors(tmp_path: Path) -> None:
    """Render the stack wrapper exactly like manual CLI usage and fail on console issues."""

    output_path = tmp_path / "pi_carrier_stack_cli.stl"
    result = subprocess.run(
        [
            "openscad",
            "-o",
            str(output_path),
            "--export-format",
            "binstl",
            str(STACK_SCAD),
        ],
        capture_output=True,
        text=True,
    )

    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    for substring in FAILURE_SUBSTRINGS:
        assert substring not in log, f"OpenSCAD console reported: {substring}"
    assert output_path.exists()
