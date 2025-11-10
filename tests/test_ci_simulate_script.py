"""Tests for the CI simulation helper script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_ci_simulate_accepts_custom_python(tmp_path: Path) -> None:
    """The --python flag should forward pytest runs through the requested interpreter."""

    script = REPO_ROOT / "scripts" / "ci_simulate.sh"

    log_path = tmp_path / "python-invocations.log"

    fake_python = tmp_path / "fake-python"
    _write_executable(
        fake_python,
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"{log_path}"

if [ "${{1:-}}" = "--version" ]; then
  echo "Python 3.99.0"
  exit 0
fi

if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "pytest" ]; then
  if [ "${{3:-}}" = "--version" ]; then
    echo "pytest 9.99.0"
    exit 0
  fi
  exit 0
fi

exec python3 "$@"
""",
    )

    bats_stub = tmp_path / "bats"
    _write_executable(
        bats_stub,
        """#!/usr/bin/env bash
printf '1..0\n'
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"

    result = subprocess.run(
        ["bash", str(script), "--python", str(fake_python), "--skip-install"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    log_entries = log_path.read_text(encoding="utf-8").splitlines()

    assert any("--version" in entry for entry in log_entries)
    assert any("-m pytest --version" in entry for entry in log_entries)
    assert any("-m pytest" in entry and "--version" not in entry for entry in log_entries)
