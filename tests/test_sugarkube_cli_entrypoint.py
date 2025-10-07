"""Ensure the legacy wrapper script still defers to the unified CLI."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SUGARKUBE_SCRIPT = REPO_ROOT / "scripts" / "sugarkube"


def test_sugarkube_script_invokes_cli(tmp_path: Path) -> None:
    """scripts/sugarkube should exec ``python -m sugarkube_toolkit`` with passthrough args."""

    fake_python = tmp_path / "fake-python"
    args_file = tmp_path / "args.json"

    fake_python.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args_file = Path(os.environ["SUGARKUBE_TEST_ARGS_FILE"])
args_file.write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env["SUGARKUBE_PYTHON"] = str(fake_python)
    env["SUGARKUBE_TEST_ARGS_FILE"] = str(args_file)

    result = subprocess.run(
        [str(SUGARKUBE_SCRIPT), "docs", "start-here", "--path-only"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr

    recorded_args = json.loads(args_file.read_text(encoding="utf-8"))
    assert recorded_args[:2] == ["-m", "sugarkube_toolkit"]
    assert recorded_args[2:] == ["docs", "start-here", "--path-only"]


def test_sugarkube_script_sets_repo_root_from_subdirectory() -> None:
    """The wrapper should work even when launched outside the repository root."""

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "sugarkube"
    assert script.exists(), "scripts/sugarkube entry point is missing"

    result = subprocess.run(
        [str(script), "docs", "start-here", "--path-only"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root / "tests",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("docs/start-here.md"), result.stdout
