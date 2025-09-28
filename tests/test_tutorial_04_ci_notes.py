"""Ensure Tutorial 4 reflects current CI expectations."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "tutorials"
    / "tutorial-04-version-control-collaboration.md"
)


def test_ci_notes_references_pre_commit_command() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "`pre-commit run --all-files`" in text
    ), "Tutorial 4 should direct readers to run pre-commit"


def test_ci_notes_no_longer_mark_pre_commit_as_planned() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "planned for Sugarkube contributions" not in text
    ), "Tutorial 4 still labels pre-commit usage as future work"


def test_ci_notes_reference_pyspelling_command() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "`pyspelling -c .spellcheck.yaml`" in text
    ), "Tutorial 4 should direct readers to run pyspelling with the project config"


def test_ci_notes_reference_linkchecker_command() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "`linkchecker --no-warnings README.md docs/`" in text
    ), "Tutorial 4 should remind readers to run linkchecker before opening a PR"
