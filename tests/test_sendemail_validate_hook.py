"""Ensure the sendemail-validate hook sample reflects repo expectations."""

from __future__ import annotations

from pathlib import Path

HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "sendemail-validate.sample"


def test_sendemail_hook_runs_repo_checks() -> None:
    """The sample hook should run scripts/checks.sh when present."""

    text = HOOK_PATH.read_text(encoding="utf-8")
    assert "./scripts/checks.sh" in text, "Hook sample should run scripts/checks.sh"
