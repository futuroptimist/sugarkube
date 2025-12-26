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
    carrier_scad = scad_stub.parent / "pi_carrier.scad"
    carrier_scad.write_text("// stub carrier scad", encoding="utf-8")

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
        carrier_scad_path=carrier_scad,
        output_dir=output_dir,
        standoff_modes=DEFAULT_STANDOFF_MODES,
        fan_sizes=DEFAULT_FAN_SIZES,
    )

    expected_modes = {"printed", "heatset"}
    single_render_parts = {"post", "fan_adapter"}
    expected_fans = {"80", "92", "120"}

    assert (
        len(calls)
        == (len(expected_modes) * 2)  # carrier + preview per standoff mode
        + len(single_render_parts)  # mode-agnostic parts
        + len(expected_fans)  # fan walls
        + 1  # assembly preview
    )

    carrier_commands: list[list[str]] = []
    carrier_previews: list[list[str]] = []
    single_parts: set[str] = set()
    seen_fans: set[str] = set()
    for args in calls:
        assert "--export-format" in args
        assert "binstl" in args
        if 'export_part="fan_wall"' in args:
            fan_fragment = next((part for part in args if part.startswith("fan_size=")), None)
            assert fan_fragment is not None
            seen_fans.add(fan_fragment.split("=")[1])
            continue
        if "include_stack_mounts=true" in args:
            carrier_commands.append(args)
            continue
        if 'export_part="carrier_level"' in args:
            carrier_previews.append(args)
            continue
        if 'export_part="assembly"' in args:
            continue
        part_fragment = next((part for part in args if part.startswith('export_part="')), None)
        assert part_fragment is not None
        part_name = part_fragment.split("=")[1].strip('"')
        single_parts.add(part_name)

    for command in carrier_commands:
        mode_fragment = next((part for part in command if part.startswith('standoff_mode="')), None)
        assert mode_fragment is not None
        assert mode_fragment.split("=")[1].strip('"') in expected_modes
        assert "pi_carrier.scad" in command[-1]

    for command in carrier_previews:
        mode_fragment = next((part for part in command if part.startswith('standoff_mode="')), None)
        assert mode_fragment is not None
        assert mode_fragment.split("=")[1].strip('"') in expected_modes
        assert "pi_carrier_stack.scad" in command[-1]

    assert single_parts == single_render_parts
    assert seen_fans == expected_fans

    generated = {
        path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*.stl")
    }
    assert {
        "carriers/pi_carrier_stack_mounts_printed.stl",
        "carriers/pi_carrier_stack_mounts_heatset.stl",
        "posts/pi_carrier_stack_post.stl",
        "fan_adapters/pi_carrier_stack_fan_adapter.stl",
        "fan_walls/pi_carrier_stack_fan_wall_fan80.stl",
        "fan_walls/pi_carrier_stack_fan_wall_fan92.stl",
        "fan_walls/pi_carrier_stack_fan_wall_fan120.stl",
        "preview/pi_carrier_stack_carrier_level_printed.stl",
        "preview/pi_carrier_stack_carrier_level_heatset.stl",
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
