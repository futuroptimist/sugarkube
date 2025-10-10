"""Ensure the notes workspace exists for onboarding evidence."""

from pathlib import Path


def test_notes_directory_exists() -> None:
    """notes/ should exist so templates referencing it remain accurate."""

    notes_dir = Path("notes")
    assert notes_dir.is_dir(), "notes/ directory should exist for onboarding archives"

    readme = notes_dir / "README.md"
    assert readme.is_file(), "notes/README.md should document the workspace"

    text = readme.read_text(encoding="utf-8")
    lower = text.lower()
    assert "onboarding" in lower, "notes README should call out onboarding evidence"
    assert (
        "docs/templates/simplification/onboarding-update.md" in text
    ), "notes README should point to the onboarding update template"
    assert (
        "tests/test_notes_directory.py" in text
    ), "notes README should record the regression coverage for this workspace"
