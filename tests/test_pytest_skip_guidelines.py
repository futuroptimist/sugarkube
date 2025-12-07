"""Ensure pytest.skip calls include remediation context."""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def _iter_pytest_skip_calls(path: Path, *, source: str) -> list[int]:
    tree = ast.parse(source, filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest"
        and node.func.attr == "skip"
    ]


def test_pytest_skip_calls_document_todo_root_cause_and_fix() -> None:
    """Each pytest.skip call should include the standard remediation comment block."""

    missing: list[str] = []

    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue

        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        for lineno in _iter_pytest_skip_calls(path, source=text):
            lookback = lineno - 2
            while lookback >= 0 and lines[lookback].strip() == "":
                lookback -= 1

            comment_block: list[str] = []
            while lookback >= 0 and lines[lookback].lstrip().startswith("#"):
                comment_block.append(lines[lookback].strip())
                lookback -= 1
            comment_block.reverse()

            if not comment_block:
                missing.append(f"{path}:{lineno} lacks skip context comments")
                continue

            for prefix in ("# TODO:", "# Root cause:", "# Estimated fix:"):
                if not any(line.startswith(prefix) for line in comment_block):
                    missing.append(
                        f"{path}:{lineno} missing '{prefix}' comment before pytest.skip"
                    )

    assert not missing, "\n".join(missing)
