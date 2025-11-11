"""Ensure Bats skip directives carry the documented remediation context."""

from __future__ import annotations

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent


@pytest.mark.parametrize("bats_file", sorted(TESTS_DIR.glob("**/*.bats")))
def test_skip_comments_document_todo_root_cause_and_fix(bats_file: Path) -> None:
    """Each skip command should include a comment block per the skip guidelines."""

    lines = bats_file.read_text(encoding="utf-8").splitlines()
    missing: list[str] = []

    for index, line in enumerate(lines):
        if not line.strip().startswith("skip "):
            continue

        comment_block: list[str] = []
        lookback = index - 1
        while lookback >= 0 and lines[lookback].strip() == "":
            lookback -= 1

        while lookback >= 0 and lines[lookback].lstrip().startswith("#"):
            comment_block.append(lines[lookback].strip())
            lookback -= 1

        comment_block.reverse()

        if not comment_block:
            missing.append(f"{bats_file}:{index + 1} lacks skip context comments")
            continue

        for prefix in ("# TODO:", "# Root cause:", "# Estimated fix:"):
            if not any(line.startswith(prefix) for line in comment_block):
                missing.append(
                    f"{bats_file}:{index + 1} missing '{prefix}' comment before skip"
                )

    assert not missing, "\n".join(missing)
