"""Ensure justfile conforms to formatter requirements."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_justfile_formatting() -> None:
    """The justfile should pass just --unstable --fmt --check."""
    repo_root = Path(__file__).resolve().parents[1]
    justfile_path = repo_root / "justfile"

    assert justfile_path.exists(), "justfile should exist"

    if not shutil.which("just"):
        # TODO: Install the just binary in the dev environment or vendor a portable build.
        # Root cause: The formatter check relies on just, which is not guaranteed on minimal
        #   base images or Windows environments without the toolchain.
        # Estimated fix: 1h to add just to the CI bootstrap and document a local install step.
        pytest.skip("just is not installed")

    result = subprocess.run(
        ["just", "--unstable", "--fmt", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"Justfile formatting check failed. Run 'just --unstable --fmt' to fix.\n"
        f"Diff:\n{result.stdout}"
    )
