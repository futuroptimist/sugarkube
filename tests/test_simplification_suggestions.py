"""Ensure simplification_suggestions.md reflects shipped CLI coverage."""

from __future__ import annotations

from pathlib import Path

DOC_PATH = Path(__file__).resolve().parents[1] / "simplification_suggestions.md"


def test_cli_follow_up_subcommands_documented_as_shipped() -> None:
    """The backlog entry should no longer frame CLI subcommands as future work."""

    text = DOC_PATH.read_text(encoding="utf-8")
    assert (
        "Follow-up subcommands will wrap the image and Pi automation" not in text
    ), "Simplification backlog still frames CLI wrappers as future work"
    assert (
        "Follow-up subcommands now wrap" in text
    ), "Simplification backlog should confirm CLI wrappers are already available"
