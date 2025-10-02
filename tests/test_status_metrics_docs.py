"""Ensure the telemetry metrics archive described in the docs exists."""

from __future__ import annotations

from pathlib import Path

METRICS_DIR = Path(__file__).resolve().parents[1] / "docs" / "status" / "metrics"
README_PATH = METRICS_DIR / "README.md"


def test_metrics_directory_exists() -> None:
    """docs/status/metrics/ should be present for telemetry snapshots."""

    assert METRICS_DIR.exists(), "docs/status/metrics directory is missing"
    assert README_PATH.exists(), "docs/status/metrics/README.md is missing"


def test_metrics_readme_guides_publish_telemetry() -> None:
    """The README should explain how to generate snapshot markdown files."""

    text = README_PATH.read_text(encoding="utf-8")
    assert (
        "scripts/publish_telemetry.py" in text
    ), "README should reference scripts/publish_telemetry.py"
    assert "--markdown-dir" in text, "README should document the --markdown-dir flag"
    assert (
        "SUGARKUBE_TELEMETRY_MARKDOWN_DIR" in text
    ), "README should mention the SUGARKUBE_TELEMETRY_MARKDOWN_DIR environment variable"
