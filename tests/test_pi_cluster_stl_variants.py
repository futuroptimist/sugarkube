"""Ensure pi_carrier_stack STL variants render across documented combinations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

import pytest

from scripts.render_pi_cluster_variants import (
    DEFAULT_FAN_SIZES,
    DEFAULT_STANDOFF_MODES,
    render_variants,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "render_pi_cluster_variants.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "scad-to-stl.yml"


def test_render_pi_cluster_variants_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper should invoke OpenSCAD for each stack part and fan size."""

    assert (
        SCRIPT_PATH.exists()
    ), "Add scripts/render_pi_cluster_variants.py so CI can render the documented STL matrix"

    scad_stub = tmp_path / "pi_carrier_stack.scad"
    scad_stub.write_text("// stub scad", encoding="utf-8")

    output_dir = tmp_path / "stl" / "pi_cluster"
    calls: list[list[str]] = []

    def _stub_run(command: Iterable[str], check: bool = False) -> subprocess.CompletedProcess[str]:
        args = list(command)
        calls.append(args)
        if "-o" in args:
            output = Path(args[args.index("-o") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("stub", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setenv("OPENSCAD_LOG", "unused")
    monkeypatch.setattr(subprocess, "run", _stub_run)

    render_variants(
        openscad="openscad-bin",
        scad_path=scad_stub,
        output_dir=output_dir,
        standoff_modes=DEFAULT_STANDOFF_MODES,
        fan_sizes=DEFAULT_FAN_SIZES,
    )

    expected_modes = {"printed", "heatset"}
    single_render_parts = {"post", "fan_adapter"}
    expected_carrier_part = "carrier_level"
    expected_fans = {"80", "92", "120"}

    assert (
        len(calls)
        == len(expected_modes)  # carriers per standoff mode
        + len(single_render_parts)  # mode-agnostic parts
        + len(expected_fans)  # fan walls
        + 1  # preview
    )

    seen_carrier_parts: set[tuple[str, str]] = set()
    seen_single_parts: set[str] = set()
    seen_fans: set[str] = set()
    for args in calls:
        assert "--export-format" in args
        assert "binstl" in args
        if 'export_part="fan_wall"' in args:
            fan_fragment = next((part for part in args if part.startswith("fan_size=")), None)
            assert fan_fragment is not None
            seen_fans.add(fan_fragment.split("=")[1])
            continue
        if 'export_part="assembly"' in args:
            continue
        part_fragment = next((part for part in args if part.startswith('export_part="')), None)
        assert part_fragment is not None
        part_name = part_fragment.split("=")[1].strip('"')
        if part_name == expected_carrier_part:
            mode_fragment = next((part for part in args if part.startswith('standoff_mode="')), None)
            assert mode_fragment is not None
            mode_name = mode_fragment.split("=")[1].strip('"')
            assert mode_name in expected_modes
            seen_carrier_parts.add((part_name, mode_name))
        else:
            assert part_name in single_render_parts
            assert 'standoff_mode="' not in args
            seen_single_parts.add(part_name)

    assert seen_carrier_parts == {(expected_carrier_part, mode) for mode in expected_modes}
    assert seen_single_parts == single_render_parts
    assert seen_fans == expected_fans

    generated = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*.stl")}
    assert {
        "carriers/printed/pi_carrier_stack_carrier_level_printed.stl",
        "carriers/heatset/pi_carrier_stack_carrier_level_heatset.stl",
        "posts/pi_carrier_stack_post.stl",
        "fan_adapters/pi_carrier_stack_fan_adapter.stl",
        "fan_walls/pi_carrier_stack_fan_wall_fan80.stl",
        "fan_walls/pi_carrier_stack_fan_wall_fan92.stl",
        "fan_walls/pi_carrier_stack_fan_wall_fan120.stl",
        "preview/pi_carrier_stack_preview.stl",
    }.issubset(generated)


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
