"""Ensure docs verification wrappers call the unified CLI directly."""

from __future__ import annotations

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
