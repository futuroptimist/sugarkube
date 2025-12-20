from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
FAIL_SUBSTRINGS = [
    "undefined operation",
    "Unable to convert translate",
    "max() parameter could not be converted",
    "min() parameter could not be converted",
]

pytestmark = pytest.mark.skipif(
    shutil.which("openscad") is None, reason="openscad binary not available"
)


def test_stack_entrypoint_matches_ci_render(tmp_path: Path) -> None:
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
    assert output_path.exists()
    for substring in FAIL_SUBSTRINGS:
        assert substring not in log
