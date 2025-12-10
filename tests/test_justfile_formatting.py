"""Ensure justfile conforms to formatter requirements."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.support.just_installer import ensure_just_available


def test_justfile_formatting() -> None:
    """The justfile should pass just --unstable --fmt --check."""
    repo_root = Path(__file__).resolve().parents[1]
    justfile_path = repo_root / "justfile"

    assert justfile_path.exists(), "justfile should exist"

    just_path = ensure_just_available()
    env = os.environ.copy()
    env["PATH"] = f"{just_path.parent}:{env.get('PATH', '')}"

    result = subprocess.run(
        [str(just_path), "--unstable", "--fmt", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, (
        f"Justfile formatting check failed. Run 'just --unstable --fmt' to fix.\n"
        f"Diff:\n{result.stdout}"
    )
