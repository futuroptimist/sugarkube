"""Ensure docs explain the CLI's repository-root working directory."""

from __future__ import annotations

from pathlib import Path


def test_readme_calls_out_repo_root_execution() -> None:
    """The README should mention the enforced repository-root working directory."""

    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert "repository root" in readme_text and "CLI" in readme_text


def test_contributor_map_calls_out_repo_root_execution() -> None:
    """The contributor script map should reiterate the repository-root requirement."""

    doc_text = Path("docs/contributor_script_map.md").read_text(encoding="utf-8")

    assert "repository root" in doc_text and "CLI" in doc_text


def test_readme_points_to_sugarkube_wrapper_for_nested_usage() -> None:
    """Readers should learn to use scripts/sugarkube when not at repo root."""

    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert "scripts/sugarkube" in readme_text, "README should mention the wrapper for nested usage"
