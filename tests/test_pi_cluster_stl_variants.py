"""Ensure pi_carrier_stack STL variants render across documented combinations."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "render_pi_cluster_variants.py"
SCAD_PATH = REPO_ROOT / "cad" / "pi_cluster" / "pi_carrier_stack.scad"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "scad-to-stl.yml"


def _write_stub_openscad(path: Path, log_file: Path) -> None:
    script = """#!/usr/bin/env python3
import os
import sys
from pathlib import Path


log_path = Path(os.environ[\"OPENSCAD_LOG\"])
args = sys.argv[1:]
output = None
for idx, arg in enumerate(args):
    if arg == \"-o\":
        output = Path(args[idx + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(\"stub\", encoding=\"utf-8\")
        break

if output is None:
    raise SystemExit(\"openscad stub expected an -o argument\")

with log_path.open(\"a\", encoding=\"utf-8\") as handle:
    handle.write(\" ".join(args) + \"\\n\")
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def test_render_pi_cluster_variants_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper should invoke OpenSCAD for carriers, posts, fans, and adapters."""

    assert (
        SCRIPT_PATH.exists()
    ), "Add scripts/render_pi_cluster_variants.py so CI can render the documented STL matrix"

    log_file = tmp_path / "openscad.log"
    stub_bin = tmp_path / "openscad"
    _write_stub_openscad(stub_bin, log_file)

    monkeypatch.setenv("OPENSCAD_LOG", str(log_file))

    output_dir = tmp_path / "stl"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--openscad",
            str(stub_bin),
            "--output-dir",
            str(output_dir),
            "--scad-path",
            str(SCAD_PATH),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    log_lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(log_lines) == 12, "Expected 12 invocations (2 carriers + post + 3×fan wall/adapter/assembly)."

    expected_modes = {"printed", "heatset"}
    expected_fans = {"80", "92", "120"}

    generated = {path.name for path in output_dir.glob("*.stl")}
    assert generated.issuperset(
        {
            "carrier_level_printed.stl",
            "carrier_level_heatset.stl",
            "stack_post.stl",
            *(f"fan_wall_fan{fan}.stl" for fan in expected_fans),
            *(f"fan_adapter_fan{fan}.stl" for fan in expected_fans),
            *(f"assembly_fan{fan}.stl" for fan in expected_fans),
        }
    )


def test_scad_to_stl_workflow_renders_pi_carrier_stack() -> None:
    """The STL workflow should explicitly render the pi_carrier_stack matrix."""

    assert WORKFLOW_PATH.exists(), "scad-to-stl workflow should exist to render STL artifacts"
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "render_pi_cluster_variants.py" in workflow
    assert "pi_carrier_stack" in workflow


def test_scad_to_stl_workflow_uploads_grouped_artifacts() -> None:
    """The workflow should publish grouped artifacts for builders."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    for artifact_name in (
        "stl-${{ github.sha }}",
        "stl-pi_cluster_stack-${{ github.sha }}",
        "stl-pi_cluster_carriers-${{ github.sha }}",
        "stl-sugarkube-enclosure-${{ github.sha }}",
    ):
        assert artifact_name in workflow, f"Missing upload step for {artifact_name}"

    assert "package_stl_artifacts.py" in workflow
    assert "dist/stl_artifacts" in workflow
