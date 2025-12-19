from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"


@pytest.fixture(autouse=True)
def skip_on_missing_openscad() -> None:
    if not shutil.which("openscad"):
        pytest.skip("openscad is required to render stack carrier fixtures")


def test_stack_mounts_echo_when_rendering(tmp_path: Path) -> None:
    """Carrier-level renders should emit stack mount debug info."""

    output_path = tmp_path / "carrier_level.stl"

    result = subprocess.run(
        [
            "openscad",
            "-o",
            str(output_path),
            "--export-format",
            "binstl",
            "-D",
            'export_part="carrier_level"',
            "-D",
            'standoff_mode="heatset"',
            "-D",
            "stack_edge_margin=15",
            "--",
            str(SCAD_PATH),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    log = result.stdout + result.stderr
    assert "stack_mounts_enabled" in log
    assert "include_stack_mounts = true" in log
    assert "stack_pocket_d = 9" in log
    assert output_path.exists()
    assert output_path.stat().st_size > 0
