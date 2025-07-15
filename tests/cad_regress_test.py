import shutil
import subprocess
from pathlib import Path

import pytest

SKIP = shutil.which("openscad") is None


@pytest.mark.skipif(SKIP, reason="OpenSCAD not installed")
def test_stl_generation(tmp_path):
    scad_files = list(Path("cad").rglob("*.scad"))
    assert scad_files, "no scad files found"
    for scad in scad_files:
        out = tmp_path / (scad.stem + ".stl")
        subprocess.run(["openscad", "-o", str(out), str(scad)], check=True)
        assert out.exists() and out.stat().st_size > 0
