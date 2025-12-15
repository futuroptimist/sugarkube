"""Tests for grouping STL artifacts into named bundles."""
from __future__ import annotations

from pathlib import Path

from scripts import package_stl_artifacts

ALL_STL_FILES = (
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
    "pi_carrier_printed.stl",
    "pi5_triple_carrier_rot45_printed.stl",
    "pi_carrier_heatset.stl",
    "pi5_triple_carrier_rot45_heatset.stl",
    "frame_printed.stl",
    "panel_bracket_printed.stl",
    "sugarkube_printed.stl",
    "frame_heatset.stl",
    "panel_bracket_heatset.stl",
    "sugarkube_heatset.stl",
)


def _write_stub_stls(stl_dir: Path) -> None:
    for rel_path in ALL_STL_FILES:
        target = stl_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub", encoding="utf-8")


def test_stage_artifacts_groups_outputs(tmp_path: Path) -> None:
    stl_dir = tmp_path / "stl"
    out_dir = tmp_path / "dist"
    _write_stub_stls(stl_dir)

    artifacts = package_stl_artifacts.stage_artifacts(
        stl_dir=stl_dir,
        out_dir=out_dir,
        sha="abc123",
    )

    expected_names = {
        "stl-pi_cluster_stack-abc123",
        "stl-pi_cluster_carriers-abc123",
        "stl-sugarkube-enclosure-abc123",
    }
    assert {path.name for path in artifacts} == expected_names

    stack_dir = out_dir / "stl-pi_cluster_stack-abc123"
    carriers_dir = out_dir / "stl-pi_cluster_carriers-abc123"
    enclosure_dir = out_dir / "stl-sugarkube-enclosure-abc123"

    assert (stack_dir / "printed/pi_carrier_stack_printed.stl").exists()
    assert (stack_dir / "heatset/fan_wall_heatset.stl").exists()
    assert (stack_dir / "variants/pi_carrier_stack_brass_chain_fan120.stl").exists()

    assert (carriers_dir / "printed/pi_carrier_printed.stl").exists()
    assert (carriers_dir / "heatset/pi5_triple_carrier_rot45_heatset.stl").exists()

    assert (enclosure_dir / "printed/sugarkube_printed.stl").exists()
    assert (enclosure_dir / "heatset/frame_heatset.stl").exists()

    readme_text = (stack_dir / "README.txt").read_text(encoding="utf-8")
    assert "Docs:" in readme_text
    assert package_stl_artifacts.REPO_WORKFLOW_PATH in readme_text
