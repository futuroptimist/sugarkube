"""Ensure grouped STL artifact packaging is staged as expected."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.package_stl_artifacts import WORKFLOW_PATH, _build_specs, stage_artifacts


def _write_stub_files(root: Path) -> None:
    for spec in _build_specs():
        for section_files in spec.sections.values():
            for file_spec in section_files:
                target = root / file_spec.source
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("stub", encoding="utf-8")


def test_stage_artifacts_creates_expected_tree(tmp_path: Path) -> None:
    stl_dir = tmp_path / "stl"
    out_dir = tmp_path / "dist"
    _write_stub_files(stl_dir)

    staged = stage_artifacts(stl_dir=stl_dir, out_dir=out_dir, sha="abc123")

    specs = _build_specs()
    assert len(staged) == len(specs)

    staged_by_name = {path.name: path for path in staged}
    for spec in specs:
        artifact = staged_by_name[f"{spec.base_name}-abc123"]
        assert artifact.is_dir()
        readme = artifact / "README.txt"
        assert readme.exists()
        readme_text = readme.read_text(encoding="utf-8")
        assert spec.title in readme_text
        assert str(WORKFLOW_PATH) in readme_text

        for section, files in spec.sections.items():
            for file_spec in files:
                copied = artifact / section / Path(file_spec.source).name
                assert copied.exists()
                assert copied.read_text(encoding="utf-8") == "stub"


def test_stage_artifacts_raises_when_inputs_missing(tmp_path: Path) -> None:
    stl_dir = tmp_path / "stl"
    out_dir = tmp_path / "dist"
    stl_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        stage_artifacts(stl_dir=stl_dir, out_dir=out_dir, sha="abc123")
