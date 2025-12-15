"""Unit tests for STL artifact packaging."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.package_stl_artifacts import PackagingError, package_stl_artifacts


def _touch_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub", encoding="utf-8")


def test_package_stl_artifacts_groups_files(tmp_path: Path) -> None:
    """Outputs should be grouped per use case with README guidance."""

    stl_dir = tmp_path / "stl"

    for name in [
        "pi_carrier_stack_printed.stl",
        "pi_carrier_stack_heatset.stl",
        "fan_wall_printed.stl",
        "fan_wall_heatset.stl",
        "pi_carrier_column_printed.stl",
        "pi_carrier_column_heatset.stl",
        "pi_carrier_printed.stl",
        "pi_carrier_heatset.stl",
        "pi5_triple_carrier_rot45_printed.stl",
        "pi5_triple_carrier_rot45_heatset.stl",
        "frame_printed.stl",
        "frame_heatset.stl",
        "panel_bracket_printed.stl",
        "panel_bracket_heatset.stl",
        "sugarkube_printed.stl",
        "sugarkube_heatset.stl",
    ]:
        _touch_stub(stl_dir / name)

    variant_dir = stl_dir / "pi_cluster"
    for mode in ("printed", "brass_chain"):
        for fan_size in (80, 92, 120):
            _touch_stub(variant_dir / f"pi_carrier_stack_{mode}_fan{fan_size}.stl")

    out_dir = tmp_path / "dist"
    package_stl_artifacts(stl_dir=stl_dir, out_dir=out_dir)

    stack_root = out_dir / "pi_cluster_stack"
    assert {path.name for path in (stack_root / "printed").iterdir()} == {
        "pi_carrier_stack_printed.stl",
        "fan_wall_printed.stl",
        "pi_carrier_column_printed.stl",
    }
    assert {path.name for path in (stack_root / "heatset").iterdir()} == {
        "pi_carrier_stack_heatset.stl",
        "fan_wall_heatset.stl",
        "pi_carrier_column_heatset.stl",
    }
    assert {path.name for path in (stack_root / "variants").iterdir()} == {
        "pi_carrier_stack_printed_fan80.stl",
        "pi_carrier_stack_printed_fan92.stl",
        "pi_carrier_stack_printed_fan120.stl",
        "pi_carrier_stack_brass_chain_fan80.stl",
        "pi_carrier_stack_brass_chain_fan92.stl",
        "pi_carrier_stack_brass_chain_fan120.stl",
    }

    carriers_root = out_dir / "pi_cluster_carriers"
    assert {path.name for path in (carriers_root / "printed").iterdir()} == {
        "pi_carrier_printed.stl",
        "pi5_triple_carrier_rot45_printed.stl",
    }
    assert {path.name for path in (carriers_root / "heatset").iterdir()} == {
        "pi_carrier_heatset.stl",
        "pi5_triple_carrier_rot45_heatset.stl",
    }

    enclosure_root = out_dir / "sugarkube-enclosure"
    assert {path.name for path in (enclosure_root / "printed").iterdir()} == {
        "frame_printed.stl",
        "panel_bracket_printed.stl",
        "sugarkube_printed.stl",
    }
    assert {path.name for path in (enclosure_root / "heatset").iterdir()} == {
        "frame_heatset.stl",
        "panel_bracket_heatset.stl",
        "sugarkube_heatset.stl",
    }

    readme = (stack_root / "README.txt").read_text(encoding="utf-8")
    assert "Pi cluster stack STLs" in readme
    assert "- printed/\n  - pi_carrier_stack_printed.stl" in readme
    assert "Docs:\n- docs/pi_cluster_stack.md" in readme
    assert ".github/workflows/scad-to-stl.yml" in readme


def test_package_stl_artifacts_requires_stl_dir(tmp_path: Path) -> None:
    """Missing STL directory should raise a PackagingError."""

    with pytest.raises(PackagingError, match="STL directory not found"):
        package_stl_artifacts(stl_dir=tmp_path / "missing", out_dir=tmp_path / "dist")


def test_package_stl_artifacts_requires_expected_files(tmp_path: Path) -> None:
    """Missing required STL files should raise a PackagingError."""

    stl_dir = tmp_path / "stl"
    _touch_stub(stl_dir / "pi_carrier_stack_printed.stl")

    with pytest.raises(PackagingError, match="Missing required STL"):
        package_stl_artifacts(stl_dir=stl_dir, out_dir=tmp_path / "dist")


def test_package_stl_artifacts_requires_variants(tmp_path: Path) -> None:
    """Empty variant globs should be reported to the caller."""

    stl_dir = tmp_path / "stl"
    for name in [
        "pi_carrier_stack_printed.stl",
        "pi_carrier_stack_heatset.stl",
        "fan_wall_printed.stl",
        "fan_wall_heatset.stl",
        "pi_carrier_column_printed.stl",
        "pi_carrier_column_heatset.stl",
        "pi_carrier_printed.stl",
        "pi_carrier_heatset.stl",
        "pi5_triple_carrier_rot45_printed.stl",
        "pi5_triple_carrier_rot45_heatset.stl",
        "frame_printed.stl",
        "frame_heatset.stl",
        "panel_bracket_printed.stl",
        "panel_bracket_heatset.stl",
        "sugarkube_printed.stl",
        "sugarkube_heatset.stl",
    ]:
        _touch_stub(stl_dir / name)

    with pytest.raises(
        PackagingError, match="No STL files found for pi_cluster_stack/variants"
    ):
        package_stl_artifacts(stl_dir=stl_dir, out_dir=tmp_path / "dist")
