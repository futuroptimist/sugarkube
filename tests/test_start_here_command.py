"""Ensure the start-here automation promised in docs exists."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import start_here

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "start_here.py"
DOC_PATH = REPO_ROOT / "docs" / "start-here.md"


def test_start_here_script_exists() -> None:
    """The CLI helper should exist so contributors can surface the Start Here guide."""

    assert (
        SCRIPT_PATH.exists()
    ), "scripts/start_here.py should exist to mirror the documented workflow"


def test_start_here_script_reports_doc_path() -> None:
    """The helper should emit the Start Here path for tooling or shell usage."""

    assert SCRIPT_PATH.exists(), "scripts/start_here.py should exist before invoking it"
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--path-only"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.stdout.strip() == str(DOC_PATH), "Expected the CLI to print docs/start-here.md"


def test_start_here_main_prints_contents(tmp_path, capsys, monkeypatch) -> None:
    """Calling the script without flags should surface the handbook contents."""

    guide = tmp_path / "start-here.md"
    guide.write_text("Welcome to Sugarkube", encoding="utf-8")
    monkeypatch.setattr(start_here, "DOC_PATH", guide)

    exit_code = start_here.main([])

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert lines[0] == f"Sugarkube Start Here guide: {guide}"
    assert "Welcome to Sugarkube" in captured.out


def test_start_here_main_path_only_alias(tmp_path, capsys, monkeypatch) -> None:
    """The deprecated --no-content flag should continue to emit the path."""

    guide = tmp_path / "start-here.md"
    guide.write_text("Stub", encoding="utf-8")
    monkeypatch.setattr(start_here, "DOC_PATH", guide)

    exit_code = start_here.main(["--no-content"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == str(guide)


def test_start_here_main_errors_when_missing(tmp_path, capsys, monkeypatch) -> None:
    """If the handbook disappears, the CLI should explain how to restore it."""

    missing = tmp_path / "start-here.md"
    monkeypatch.setattr(start_here, "DOC_PATH", missing)

    with pytest.raises(SystemExit) as excinfo:
        start_here.main([])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "docs/start-here.md is missing" in captured.err


def test_justfile_exposes_start_here_target() -> None:
    """The justfile should route through the unified CLI like the docs describe."""

    text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert (
        "start-here:" in text
    ), "Add a start-here recipe to the justfile so automation can call it"
    assert (
        '"{{sugarkube_cli}}" docs start-here' in text
    ), "Just start-here recipe should invoke the sugarkube CLI subcommand"
    assert (
        "{{start_here_args}}" in text
    ), "The recipe should continue forwarding START_HERE_ARGS to the CLI"


def test_makefile_exposes_start_here_target() -> None:
    """Make parity keeps docs accurate for contributors who prefer Make."""

    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "start-here:" in text, "Add a start-here target to the Makefile"
    assert (
        "$(SUGARKUBE_CLI) docs start-here" in text
    ), "Make start-here target should invoke the sugarkube CLI subcommand"
    assert (
        "$(START_HERE_ARGS)" in text
    ), "The target should continue forwarding START_HERE_ARGS to the CLI"
