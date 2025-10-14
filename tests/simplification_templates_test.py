from pathlib import Path


def test_simplification_templates_exist():
    repo_root = Path(__file__).resolve().parents[1]

    legacy_base = repo_root / "docs" / "templates" / "simplification"
    assert legacy_base.is_dir(), "docs/templates/simplification directory missing"

    prompt_templates = {
        legacy_base / "onboarding-update.md": [
            "# Onboarding Update Template",
            "## Goals",
            "## Required Artifacts",
            "## Follow-up",
        ],
        repo_root
        / "docs"
        / "prompts"
        / "codex"
        / "templates"
        / "simplification"
        / "refresh.md": [
            "# Prompt Refresh Template",
            "## Current Guidance",
            "## Proposed Changes",
            "## Verification",
        ],
        legacy_base / "simplification-sprint.md": [
            "# Simplification Sprint Template",
            "## Scope",
            "## Constraints",
            "## Success Metrics",
        ],
    }

    for path, markers in prompt_templates.items():
        assert path.is_file(), f"Missing simplification template: {path.name}"
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            assert (
                marker in content
            ), f"Template {path.name} missing section heading: {marker}"

    readme = legacy_base / "README.md"
    assert readme.is_file(), "Missing simplification templates README"
    readme_text = readme.read_text(encoding="utf-8")
    expected_references = {
        "onboarding-update.md",
        "simplification-sprint.md",
        "docs/prompts/codex/templates/simplification/refresh.md",
    }
    for expected in expected_references:
        assert (
            expected in readme_text
        ), f"README missing reference to {expected}"
