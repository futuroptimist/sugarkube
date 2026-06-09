"""Regression tests for the repository test-suite workflow."""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/tests.yml")


def _if_expressions(workflow_text: str) -> list[str]:
    """Return step/job ``if`` expressions, including folded YAML continuations."""

    expressions: list[str] = []
    lines = workflow_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if not stripped.startswith("if:"):
            index += 1
            continue

        value = stripped.removeprefix("if:").strip()
        parts: list[str] = [] if value == ">-" else [value]
        index += 1
        while index < len(lines):
            continuation = lines[index]
            continuation_stripped = continuation.strip()
            continuation_indent = len(continuation) - len(continuation.lstrip())
            if continuation_stripped and continuation_indent <= indent:
                break
            if continuation_stripped:
                parts.append(continuation_stripped)
            index += 1
        expressions.append(" ".join(parts))
    return expressions


def test_codecov_upload_does_not_reference_secrets_in_step_condition() -> None:
    """GitHub Actions rejects ``secrets`` in step-level ``if`` expressions."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    expressions = _if_expressions(workflow)

    assert expressions, "tests.yml should keep conditional steps explicit"
    assert all("secrets." not in expression for expression in expressions)
    assert "env.CODECOV_UPLOAD == 'true'" in workflow
    assert "CODECOV_AUTH: ${{ secrets.CODECOV_TOKEN }}" in workflow
