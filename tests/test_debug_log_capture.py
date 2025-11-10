from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = REPO_ROOT / "scripts" / "lib" / "debug_log_capture.sh"
SANITIZER = REPO_ROOT / "scripts" / "sanitize_debug_log.py"
COMMIT_HASH = subprocess.check_output(
    ["git", "rev-parse", "--short", "HEAD"],
    cwd=REPO_ROOT,
).decode().strip()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_debug_logs_written_and_sanitized(tmp_path: Path, exit_code: int) -> None:
    log_dir = tmp_path / "logs"
    script = tmp_path / "run.sh"
    script.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir=\"{REPO_ROOT}\"
export SAVE_DEBUG_LOGS=1
export SUGARKUBE_DEBUG_LOG_DIR=\"{log_dir}\"
export SUGARKUBE_DEBUG_LOG_SANITIZER=\"{SANITIZER}\"

source \"{LIB_PATH}\"

if debug_logs::enabled; then
    debug_logs::start \"$repo_dir\" \"pytest\"
fi

trap 'status=$?; trap - EXIT; debug_logs::finalize "$status"; exit "$status"' EXIT

echo "Authorization: Bearer topsecretvalue1234567890"
echo "Internal IP 192.168.1.15"
echo "External IP 203.0.113.42"
"""
        + (f"exit {exit_code}\n" if exit_code else "")
    )
    script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code

    logs = sorted(log_dir.glob("*.log"))
    assert len(logs) == 1
    log_path = logs[0]

    hostname = subprocess.check_output(["hostname"], text=True).strip()
    assert hostname in log_path.name
    assert COMMIT_HASH in log_path.name
    assert log_path.name.endswith("_pytest.log")
    assert re.search(r"\d{8}T\d{6}Z", log_path.name)

    content = log_path.read_text()
    assert "Authorization: Bearer [REDACTED_SECRET]" in content
    assert "Internal IP 192.168.1.15" in content
    assert "External IP [REDACTED_IP]" in content
    assert "topsecretvalue" not in content


def test_debug_logs_disabled_produces_no_files(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    script = tmp_path / "run.sh"
    script.write_text(
        f"""#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir=\"{REPO_ROOT}\"
export SAVE_DEBUG_LOGS=0
export SUGARKUBE_DEBUG_LOG_DIR=\"{log_dir}\"
export SUGARKUBE_DEBUG_LOG_SANITIZER=\"{SANITIZER}\"

source \"{LIB_PATH}\"

if debug_logs::enabled; then
    debug_logs::start \"$repo_dir\" \"pytest\"
fi

trap 'status=$?; trap - EXIT; debug_logs::finalize "$status"; exit "$status"' EXIT

echo "hello world"
"""
    )
    script.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert not log_dir.exists() or not any(log_dir.iterdir())
