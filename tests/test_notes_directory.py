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


def test_onboarding_feature_brief_stub_exists() -> None:
    """The onboarding workspace should provide a feature brief scaffold."""

    onboarding_dir = Path("notes") / "onboarding"
    assert onboarding_dir.is_dir(), "notes/onboarding/ should exist for onboarding feature briefs"

    readme = onboarding_dir / "README.md"
    assert readme.is_file(), "notes/onboarding/README.md should explain how to use the workspace"

    feature_brief = onboarding_dir / "feature-brief.md"
    assert (
        feature_brief.is_file()
    ), "Seed notes/onboarding/feature-brief.md so docs referencing it stay accurate"

    text = feature_brief.read_text(encoding="utf-8")
    assert (
        "docs/templates/simplification/onboarding-update.md" in text
    ), "Feature brief stub should link back to the onboarding update template"


def test_feature_brief_redirect_stub_exists() -> None:
    """Docs reference notes/feature-brief.md; ensure a pointer exists."""

    stub = Path("notes") / "feature-brief.md"
    assert stub.is_file(), "Add notes/feature-brief.md so tutorial references remain accurate"

    text = stub.read_text(encoding="utf-8")
    assert (
        "notes/onboarding/feature-brief.md" in text
    ), "Feature brief stub should point to notes/onboarding/feature-brief.md"
