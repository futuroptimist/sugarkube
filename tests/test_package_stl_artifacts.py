"""Unit tests for STL artifact packaging."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.package_stl_artifacts import PackagingError, package_stl_artifacts


def _touch_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub", encoding="utf-8")


def _write_required_stls(stl_dir: Path, *, include_variants: bool = True) -> None:
    for name in [
        "pi_cluster/carrier_level_printed.stl",
        "pi_cluster/carrier_level_heatset.stl",
        "pi_cluster/stack_post.stl",
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

    if include_variants:
        variant_dir = stl_dir / "pi_cluster"
        for fan_size in (80, 92, 120):
            _touch_stub(variant_dir / f"fan_wall_fan{fan_size}.stl")
            _touch_stub(variant_dir / f"fan_adapter_fan{fan_size}.stl")
            _touch_stub(variant_dir / f"assembly_fan{fan_size}.stl")


def test_package_stl_artifacts_groups_files(tmp_path: Path) -> None:
    """Outputs should be grouped per use case with README guidance."""

    stl_dir = tmp_path / "stl"

    _write_required_stls(stl_dir)

    out_dir = tmp_path / "dist"
    package_stl_artifacts(stl_dir=stl_dir, out_dir=out_dir)

    stack_root = out_dir / "pi_cluster_stack"
    assert {path.name for path in (stack_root / "carriers").iterdir()} == {
        "carrier_level_printed.stl",
        "carrier_level_heatset.stl",
    }
    assert {path.name for path in (stack_root / "posts").iterdir()} == {
        "stack_post.stl",
    }
    assert {path.name for path in (stack_root / "fan_walls").iterdir()} == {
        "fan_wall_fan80.stl",
        "fan_wall_fan92.stl",
        "fan_wall_fan120.stl",
    }
    assert {path.name for path in (stack_root / "fan_adapters").iterdir()} == {
        "fan_adapter_fan80.stl",
        "fan_adapter_fan92.stl",
        "fan_adapter_fan120.stl",
    }
    assert {path.name for path in (stack_root / "preview").iterdir()} == {
        "assembly_fan80.stl",
        "assembly_fan92.stl",
        "assembly_fan120.stl",
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
    assert "- carriers/\n  - carrier_level_printed.stl" in readme
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


def test_package_stl_artifacts_requires_fan_outputs(tmp_path: Path) -> None:
    """Empty fan wall/adapters globs should be reported to the caller."""

    stl_dir = tmp_path / "stl"
    _write_required_stls(stl_dir, include_variants=False)

    with pytest.raises(
        PackagingError, match="No STL files found for pi_cluster_stack/fan_walls"
    ):
        package_stl_artifacts(stl_dir=stl_dir, out_dir=tmp_path / "dist")


def test_main_invocation_cleans_previous_outputs(tmp_path: Path) -> None:
    """CLI should rebuild outputs and remove stale contents."""

    stl_dir = tmp_path / "stl"
    _write_required_stls(stl_dir)

    out_dir = tmp_path / "dist"
    stale_root = out_dir / "pi_cluster_stack"
    stale_root.mkdir(parents=True)
    _touch_stub(stale_root / "printed" / "old.stl")

    from scripts.package_stl_artifacts import main

    assert main([
        "--stl-dir",
        str(stl_dir),
        "--out-dir",
        str(out_dir),
    ]) == 0

    rebuilt_files = {path.name for path in (out_dir / "pi_cluster_stack" / "carriers").iterdir()}
    assert "old.stl" not in rebuilt_files
    assert rebuilt_files == {
        "carrier_level_printed.stl",
        "carrier_level_heatset.stl",
    }


def test_main_reports_cli_error(tmp_path: Path) -> None:
    """CLI should surface PackagingError messages via argparse."""

    from scripts.package_stl_artifacts import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--stl-dir", str(tmp_path / "missing")])

    assert excinfo.value.code == 2
