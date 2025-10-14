from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REQUIRED_TOOLS = ("xz", "bsdtar", "gzip", "sha256sum")


def test_artifact_detection_shell_script(tmp_path: Path) -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"missing tools required for artifact detection test: {', '.join(missing)}")

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.setdefault("TMPDIR", str(tmp_path))

    result = subprocess.run(
        ["bash", "tests/artifact_detection_test.sh"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(
            "artifact detection script failed:\n"
            f"stdout:\n{result.stdout}\n--- stderr ---\n{result.stderr}",
        )
