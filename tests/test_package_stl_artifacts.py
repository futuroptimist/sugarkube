"""Regression tests for the STL artifact packager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/package_stl_artifacts.py")


def _touch_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub", encoding="utf-8")


def _source_inputs() -> dict[str, tuple[str, ...]]:
    return {
        "stack": (
            "pi_carrier_stack_printed.stl",
            "fan_wall_printed.stl",
            "pi_carrier_column_printed.stl",
            "pi_carrier_stack_heatset.stl",
            "fan_wall_heatset.stl",
            "pi_carrier_column_heatset.stl",
            "pi_cluster/pi_carrier_stack_printed_fan80.stl",
            "pi_cluster/pi_carrier_stack_printed_fan92.stl",
            "pi_cluster/pi_carrier_stack_printed_fan120.stl",
            "pi_cluster/pi_carrier_stack_brass_chain_fan80.stl",
            "pi_cluster/pi_carrier_stack_brass_chain_fan92.stl",
            "pi_cluster/pi_carrier_stack_brass_chain_fan120.stl",
        ),
        "carriers": (
            "pi_carrier_printed.stl",
            "pi5_triple_carrier_rot45_printed.stl",
            "pi_carrier_heatset.stl",
            "pi5_triple_carrier_rot45_heatset.stl",
        ),
        "enclosure": (
            "frame_printed.stl",
            "panel_bracket_printed.stl",
            "sugarkube_printed.stl",
            "frame_heatset.stl",
            "panel_bracket_heatset.stl",
            "sugarkube_heatset.stl",
        ),
    }


def _staged_outputs() -> dict[str, tuple[str, ...]]:
    return {
        "stack": (
            "printed/pi_carrier_stack_printed.stl",
            "printed/fan_wall_printed.stl",
            "printed/pi_carrier_column_printed.stl",
            "heatset/pi_carrier_stack_heatset.stl",
            "heatset/fan_wall_heatset.stl",
            "heatset/pi_carrier_column_heatset.stl",
            "variants/pi_carrier_stack_printed_fan80.stl",
            "variants/pi_carrier_stack_printed_fan92.stl",
            "variants/pi_carrier_stack_printed_fan120.stl",
            "variants/pi_carrier_stack_brass_chain_fan80.stl",
            "variants/pi_carrier_stack_brass_chain_fan92.stl",
            "variants/pi_carrier_stack_brass_chain_fan120.stl",
        ),
        "carriers": (
            "printed/pi_carrier_printed.stl",
            "printed/pi5_triple_carrier_rot45_printed.stl",
            "heatset/pi_carrier_heatset.stl",
            "heatset/pi5_triple_carrier_rot45_heatset.stl",
        ),
        "enclosure": (
            "printed/frame_printed.stl",
            "printed/panel_bracket_printed.stl",
            "printed/sugarkube_printed.stl",
            "heatset/frame_heatset.stl",
            "heatset/panel_bracket_heatset.stl",
            "heatset/sugarkube_heatset.stl",
        ),
    }


def test_package_artifacts_layout(tmp_path: Path) -> None:
    stl_root = tmp_path / "stl"
    out_dir = tmp_path / "dist"

    for filename in sum(_source_inputs().values(), tuple()):
        _touch_stub(stl_root / filename)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--stl-dir",
            str(stl_root),
            "--out-dir",
            str(out_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    stack_root = out_dir / "stl-pi_cluster_stack"
    carriers_root = out_dir / "stl-pi_cluster_carriers"
    enclosure_root = out_dir / "stl-sugarkube-enclosure"

    for dest_root, expected in (
        (stack_root, _staged_outputs()["stack"]),
        (carriers_root, _staged_outputs()["carriers"]),
        (enclosure_root, _staged_outputs()["enclosure"]),
    ):
        assert dest_root.exists()
        assert (dest_root / "README.txt").exists()
        for rel_path in expected:
            path = dest_root / rel_path
            assert path.exists(), f"Missing staged file: {path}"

    stack_readme = (stack_root / "README.txt").read_text(encoding="utf-8")
    assert "docs/pi_cluster_stack.md" in stack_readme
    assert ".github/workflows/scad-to-stl.yml" in stack_readme
