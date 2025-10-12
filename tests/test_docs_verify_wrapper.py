"""Ensure docs verification wrappers call the unified CLI directly."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_docs_verify_wrappers_invoke_unified_cli() -> None:
    """Make and Just should shell directly into the sugarkube CLI."""

    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"

    assert not (
        scripts_dir / "docs_verify.sh"
    ).exists(), (
        "Legacy shell wrapper should be removed once docs-verify wrappers migrate to the CLI"
    )
    assert not (
        scripts_dir / "docs_verify.ps1"
    ).exists(), "PowerShell wrapper should be removed alongside the shell script"

    makefile_text = (repo_root / "Makefile").read_text(encoding="utf-8")
    justfile_text = (repo_root / "justfile").read_text(encoding="utf-8")

    assert (
        "SUGARKUBE_CLI ?= $(CURDIR)/scripts/sugarkube" in makefile_text
    ), "Makefile should default docs-verify to the sugarkube CLI wrapper"
    assert (
        "$(SUGARKUBE_CLI) docs verify" in makefile_text
    ), "Makefile docs-verify target should invoke the CLI subcommand"

    assert (
        'justfile_directory() + "/scripts/sugarkube"' in justfile_text
    ), "Justfile should expose a SUGARKUBE_CLI override pointing at scripts/sugarkube"
    assert (
        '"{{sugarkube_cli}}" docs verify' in justfile_text
    ), "Just docs-verify recipe should call the CLI subcommand"


def test_docs_simplify_wrappers_invoke_unified_cli() -> None:
    """Docs simplify wrappers should also delegate to the unified CLI."""

    repo_root = Path(__file__).resolve().parents[1]
    makefile_text = (repo_root / "Makefile").read_text(encoding="utf-8")
    justfile_text = (repo_root / "justfile").read_text(encoding="utf-8")

    assert (
        "DOCS_SIMPLIFY_ARGS ?=" in makefile_text
    ), "Expose DOCS_SIMPLIFY_ARGS so the Make target can pass CLI flags"
    assert (
        "$(SUGARKUBE_CLI) docs simplify" in makefile_text
    ), "Make docs-simplify target should call the sugarkube CLI subcommand"

    assert (
        "simplify_docs_args := env_var_or_default" in justfile_text
    ), "Expose SIMPLIFY_DOCS_ARGS so the Just recipe mirrors Make"
    assert (
        '"{{sugarkube_cli}}" docs simplify' in justfile_text
    ), "Just simplify-docs recipe should invoke the CLI subcommand"


def test_make_docs_verify_runs_cli() -> None:
    """The Makefile target should execute the CLI in dry-run mode."""

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["make", "docs-verify", "DOCS_VERIFY_ARGS=--dry-run"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "$ pyspelling -c .spellcheck.yaml" in result.stdout
    assert "$ linkchecker --no-warnings README.md docs/" in result.stdout


def test_make_docs_simplify_runs_cli() -> None:
    """The docs-simplify target should proxy through the CLI in dry-run mode."""

    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["make", "docs-simplify", "DOCS_SIMPLIFY_ARGS=--dry-run"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "$ bash" in result.stdout
    assert "scripts/checks.sh --docs-only" in result.stdout
