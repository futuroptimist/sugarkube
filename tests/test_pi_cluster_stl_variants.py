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

    scad_dir = tmp_path / "cad" / "pi_cluster"
    scad_dir.mkdir(parents=True)
    scad_stub = scad_dir / "pi_carrier_stack.scad"
    scad_stub.write_text("// stack stub", encoding="utf-8")
    for name in ("pi_carrier.scad", "pi_stack_fan_adapter.scad", "fan_wall.scad"):
        (scad_dir / name).write_text(f"// {name}", encoding="utf-8")

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
    expected_fans = {"80", "92", "120"}

    assert (
        len(calls)
        == 2 * len(expected_modes)  # carriers + carrier preview per mode
        + 1  # posts
        + 1  # fan adapter
        + len(expected_fans)  # fan walls
        + 1  # assembly preview
    )

    seen_carriers: set[str] = set()
    seen_previews: set[str] = set()
    seen_fans: set[str] = set()
    saw_post = False
    saw_adapter = False
    saw_preview = False
    for args in calls:
        assert "--export-format" in args
        assert "binstl" in args
        target_scad = Path(args[-1])
        if target_scad.name == "pi_carrier.scad":
            mode_fragment = next(
                (part for part in args if part.startswith('standoff_mode="')),
                None,
            )
            assert mode_fragment is not None
            seen_carriers.add(mode_fragment.split("=")[1].strip('"'))
            assert "include_stack_mounts=true" in args
            continue
        if target_scad.name == "pi_carrier_stack.scad":
            part_fragment = next(
                (part for part in args if part.startswith('export_part="')),
                None,
            )
            assert part_fragment is not None
            part_name = part_fragment.split("=")[1].strip('"')
            if part_name == "carrier_level":
                mode_fragment = next(
                    (part for part in args if part.startswith('standoff_mode="')),
                    None,
                )
                assert mode_fragment is not None
                seen_previews.add(mode_fragment.split("=")[1].strip('"'))
            else:
                assert part_name == "post" or part_name == "assembly"
                if part_name == "post":
                    saw_post = True
                if part_name == "assembly":
                    saw_preview = True
            continue
        if target_scad.name == "pi_stack_fan_adapter.scad":
            saw_adapter = True
            continue
        if target_scad.name == "fan_wall.scad":
            fan_fragment = next(
                (part for part in args if part.startswith("fan_size=")),
                None,
            )
            assert fan_fragment is not None
            seen_fans.add(fan_fragment.split("=")[1])
            continue
        pytest.fail(f"Unexpected render command: {args}")

    assert seen_carriers == expected_modes
    assert seen_previews == expected_modes
    assert saw_post
    assert saw_adapter
    assert saw_preview
    assert seen_fans == expected_fans

    generated = {
        path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*.stl")
    }
    assert {
        "carriers/pi_carrier_stack_printed.stl",
        "carriers/pi_carrier_stack_heatset.stl",
        "preview/pi_carrier_stack_carrier_level_printed.stl",
        "preview/pi_carrier_stack_carrier_level_heatset.stl",
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
