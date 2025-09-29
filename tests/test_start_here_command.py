"""Ensure the start-here automation promised in docs exists."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def test_justfile_exposes_start_here_target() -> None:
    """The justfile should provide a start-here recipe like the docs describe."""

    text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert (
        "start-here:" in text
    ), "Add a start-here recipe to the justfile so automation can call it"
    assert "scripts/start_here.py" in text, "The just target should invoke scripts/start_here.py"


def test_makefile_exposes_start_here_target() -> None:
    """Make parity keeps docs accurate for contributors who prefer Make."""

    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "start-here:" in text, "Add a start-here target to the Makefile"
    assert "scripts/start_here.py" in text, "The Make target should invoke scripts/start_here.py"
