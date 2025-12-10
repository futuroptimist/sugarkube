"""Ensure justfile conforms to formatter requirements."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.usefixtures("ensure_just_available")
def test_justfile_formatting() -> None:
    """The justfile should pass just --unstable --fmt --check."""
    repo_root = Path(__file__).resolve().parents[1]
    justfile_path = repo_root / "justfile"

    assert justfile_path.exists(), "justfile should exist"

    assert shutil.which("just"), "just should be installed for formatting checks"

    env = os.environ.copy()

    result = subprocess.run(
        ["just", "--unstable", "--fmt", "--check"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Justfile formatting check failed. Run 'just --unstable --fmt' to fix.\n"
        f"Diff:\n{result.stdout}"
    )
