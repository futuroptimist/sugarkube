"""Helpers to install the just binary for tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[Path] = REPO_ROOT / "scripts" / "install_just.sh"


_JUST_PATH: Path | None = None


def ensure_just_available() -> Path:
    """Install just into a temporary directory if it is not already present.

    Returns the path to the usable just executable.
    """

    global _JUST_PATH

    if _JUST_PATH and _JUST_PATH.exists():
        return _JUST_PATH

    existing = shutil.which("just")
    if existing:
        _JUST_PATH = Path(existing)
        return _JUST_PATH

    prefix = Path(tempfile.mkdtemp(prefix="just-bin-"))
    env = os.environ.copy()
    env["JUST_INSTALL_PREFIX"] = str(prefix)

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    if result.returncode != 0:
        summary = (
            f"exit {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        raise RuntimeError(f"Failed to install just: {summary}")

    just_path = prefix / "just"
    if not just_path.exists():
        raise RuntimeError("install_just.sh did not create the just binary")

    _JUST_PATH = just_path
    return just_path
