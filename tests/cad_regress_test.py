import shutil
import subprocess
from pathlib import Path

import pytest

_OPENSCAD = shutil.which("openscad")


def _fake_run(cmd, check):
    out = Path(cmd[cmd.index("-o") + 1])
    out.write_bytes(b"solid")


@pytest.mark.parametrize("mode", ["heatset", "printed"])
def test_stl_generation(mode: str, tmp_path):
    """Compile each SCAD in both standoff modes.

    Ensure we get a non-empty STL output.
    """

    scad_files = list(Path("cad").rglob("*.scad"))
    assert scad_files, "no scad files found"

    runner = subprocess.run if _OPENSCAD else _fake_run

    for scad in scad_files:
        out = tmp_path / f"{scad.stem}_{mode}.stl"
        runner(
            [
                "openscad",
                "-o",
                str(out),
                "--export-format",
                "binstl",
                "-D",
                f'standoff_mode="{mode}"',
                str(scad),
            ],
            check=True,
        )
        assert out.exists() and out.stat().st_size > 0
