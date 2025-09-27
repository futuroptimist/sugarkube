from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "status" / "README.md"


def test_status_readme_exists() -> None:
    assert DOC_PATH.exists(), "docs/status/README.md is missing"


def test_status_readme_lists_core_kpis() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "## Ergonomics KPIs" in text
    required_sections = [
        "### Image build duration",
        "### Smoke-test pass rate",
        "### Onboarding checklist completion time",
    ]
    for heading in required_sections:
        assert heading in text, f"Expected heading '{heading}' in docs/status/README.md"


def test_status_readme_calls_out_measurement_sources() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    expected_phrases = [
        "pi-image workflow",
        "pi_smoke_test",
        "tutorial artifacts",
    ]
    for phrase in expected_phrases:
        assert phrase in text, f"Expected phrase '{phrase}' describing measurement guidance"
