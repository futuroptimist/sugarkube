from pathlib import Path


def test_simplification_templates_exist():
    base = Path(__file__).resolve().parents[1] / "docs" / "templates" / "simplification"
    assert base.is_dir(), "docs/templates/simplification directory missing"

    templates = {
        "onboarding-update.md": [
            "# Onboarding Update Template",
            "## Goals",
            "## Required Artifacts",
            "## Follow-up",
        ],
        "prompt-refresh.md": [
            "# Prompt Refresh Template",
            "## Current Guidance",
            "## Proposed Changes",
            "## Verification",
        ],
        "simplification-sprint.md": [
            "# Simplification Sprint Template",
            "## Scope",
            "## Constraints",
            "## Success Metrics",
        ],
    }

    for name, markers in templates.items():
        path = base / name
        assert path.is_file(), f"Missing simplification template: {name}"
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker in content, f"Template {name} missing section heading: {marker}"

    readme = base / "README.md"
    assert readme.is_file(), "Missing simplification templates README"
    readme_text = readme.read_text(encoding="utf-8")
    for expected in templates:
        assert expected in readme_text, f"README missing reference to {expected}"
