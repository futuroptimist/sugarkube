from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.openscad_echo import run_openscad_with_output


REPO_ROOT = Path(__file__).resolve().parents[1]
STACK_SCAD = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
OPENSCAD = shutil.which("openscad")


@pytest.mark.skipif(OPENSCAD is None, reason="openscad binary not available")
@pytest.mark.parametrize(
    "definitions",
    [
        {"export_part": "post"},
        {"export_part": "post", "post_quality": "ultra_draft"},
        {"export_part": "post", "post_quality": "print"},
    ],
)
def test_post_export_and_quality_modes_render_without_warnings(definitions: dict[str, object]) -> None:
    stdout, stderr = run_openscad_with_output(
        STACK_SCAD,
        definitions,
        openscad_path=str(OPENSCAD),
    )

    combined = (stdout or "") + (stderr or "")
    assert "warning" not in combined.lower(), f"OpenSCAD emitted warnings:\n{combined}"
