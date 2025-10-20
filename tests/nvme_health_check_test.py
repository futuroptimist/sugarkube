"""Regression tests for scripts/nvme_health_check.sh."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "nvme_health_check.sh"


def _write_nvme_stub(path: Path, *, fail_json: bool = False) -> None:
    """Create an nvme CLI stub that serves deterministic SMART data."""

    path.parent.mkdir(parents=True, exist_ok=True)
    script = """#!/usr/bin/env bash
set -euo pipefail

if [[ "$1" != "smart-log" ]]; then
  echo "unexpected command: $*" >&2
  exit 1
fi
shift

device="$1"
shift || true

if [[ "${1:-}" == "--output-format=json" ]]; then
  if [[ "${fail_json}" == "1" ]]; then
    echo "json export unsupported" >&2
    exit 2
  fi
  cat <<'JSON'
{
  "critical_warning" : 0,
  "percentage_used" : 12,
  "data_units_written" : 12345,
  "media_errors" : 0,
  "unsafe_shutdowns" : 0
}
JSON
  exit 0
fi

cat <<'TEXT'
Smart Log for NVME device:nvme0n1 namespace-id:ffffffff
critical_warning                    : 0x00
percentage_used                     : 12%
data_units_written                  : 12345
media_errors                        : 0
unsafe_shutdowns                    : 0
TEXT
"""
    script = script.replace("${fail_json}", "1" if fail_json else "0")
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _write_bc_stub(path: Path) -> None:
    """Write a tiny bc replacement that supports comparison checks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    script = """#!/usr/bin/env python3
import sys

expression = sys.stdin.read().strip()
if not expression:
    sys.exit(0)
expression = expression.replace("^", "**")
expression = expression.replace("&&", " and ")
expression = expression.replace("||", " or ")
result = eval(expression, {"__builtins__": {}}, {})
print(1 if result else 0)
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _prepare_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    return_env = os.environ.copy()
    return_env["PATH"] = f"{bin_dir}:{return_env['PATH']}"
    return return_env, bin_dir


def _run_script(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def test_nvme_health_writes_json_snapshot(tmp_path: Path) -> None:
    """The helper should export SMART data as JSON when requested."""

    env, bin_dir = _prepare_env(tmp_path)
    _write_nvme_stub(bin_dir / "nvme")
    _write_bc_stub(bin_dir / "bc")

    json_path = tmp_path / "smart.json"
    env["NVME_JSON_PATH"] = str(json_path)

    result = _run_script(env)

    assert result.returncode == 0, result.stderr
    assert json_path.exists(), result.stdout

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["percentage_used"] == 12
    assert "Wrote NVMe SMART JSON" in result.stdout


def test_nvme_health_json_export_failure(tmp_path: Path) -> None:
    """Failures exporting JSON should surface a non-zero exit code."""

    env, bin_dir = _prepare_env(tmp_path)
    _write_nvme_stub(bin_dir / "nvme", fail_json=True)
    _write_bc_stub(bin_dir / "bc")

    env["NVME_JSON_PATH"] = str(tmp_path / "smart.json")

    result = _run_script(env)

    assert result.returncode != 0
    assert "Failed to export NVMe SMART JSON" in result.stdout
