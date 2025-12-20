from __future__ import annotations

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

    assert result.returncode == 0
    for term in (
        "undefined operation",
        "Unable to convert translate",
        "max() parameter could not be converted",
        "min() parameter could not be converted",
    ):
        assert term not in combined_output
