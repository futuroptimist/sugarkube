"""Ensure token-place sample wrappers use the unified CLI."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_makefile_token_place_samples_invokes_cli() -> None:
    makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert (
        "$(SUGARKUBE_CLI) token-place samples" in makefile_text
    ), "Make token-place-samples target should invoke the sugarkube CLI"


def test_justfile_token_place_samples_invokes_cli() -> None:
    justfile_text = (REPO_ROOT / "justfile").read_text(encoding="utf-8")
    assert (
        '"{{sugarkube_cli}}" token-place samples' in justfile_text
    ), "Just token-place-samples recipe should use the CLI subcommand"
    assert (
        '"{{ sugarkube_cli }}" token-place samples' not in justfile_text
    ), "Whitespace around sugarkube_cli should be stripped to aid detection"


def test_taskfile_token_place_samples_invokes_cli() -> None:
    taskfile_text = (REPO_ROOT / "Taskfile.yml").read_text(encoding="utf-8")
    assert (
        "token-place samples" in taskfile_text and "{{.SUGARKUBE_CLI}}" in taskfile_text
    ), "Task token-place:samples command should delegate to the sugarkube CLI"
