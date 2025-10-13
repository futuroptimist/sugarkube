"""Ensure the workflow notification guide references the unified CLI."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "pi_workflow_notifications.md"


def test_doc_mentions_cli_wrapper() -> None:
    """The guide should advertise the CLI and task runner shortcuts."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert "python -m sugarkube_toolkit notify workflow" in text
    assert "task notify:workflow" in text
