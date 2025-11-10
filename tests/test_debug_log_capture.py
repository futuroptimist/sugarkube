from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEBUG_LIB = REPO_ROOT / "scripts" / "lib" / "debug_logs.sh"


def _run_debug_script(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    wrapped = textwrap.dedent(
        f"""
        set -euo pipefail
        source "{DEBUG_LIB}"
        {script}
        """
    )
    return subprocess.run(  # noqa: PLW1510
        ["bash", "-c", wrapped],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_debug_log_filename_contains_commit_and_timestamp(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["SUGARKUBE_SAVE_DEBUG_LOGS"] = "1"
    env["SUGARKUBE_DEBUG_LOG_DIR"] = str(tmp_path)

    _run_debug_script(
        """
        debug_logs::start "$(pwd)" "just-up-dev"
        echo "bootstrap running"
        debug_logs::finalize 0
        """,
        env,
    )

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    log_path = files[0]

    commit = subprocess.check_output(  # noqa: S603
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()

    assert commit in log_path.name
    assert re.search(r"\d{8}T\d{6}Z", log_path.name)
    assert "bootstrap running" in log_path.read_text(encoding="utf-8")


def test_debug_log_redacts_secrets_and_public_ips(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["SUGARKUBE_SAVE_DEBUG_LOGS"] = "1"
    env["SUGARKUBE_DEBUG_LOG_DIR"] = str(tmp_path)
    env["SUGARKUBE_TOKEN_DEV"] = "shhhh-secret"
    env["SERVICE_KEY"] = "service-secret"

    _run_debug_script(
        """
        debug_logs::start "$(pwd)" "just-up-dev"
        echo "token ${SUGARKUBE_TOKEN_DEV}"
        echo "key ${SERVICE_KEY}" >&2
        echo "public 8.8.8.8" >&2
        echo "private 192.168.5.6"
        debug_logs::finalize 0
        """,
        env,
    )

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    log_text = files[0].read_text(encoding="utf-8")

    assert "shhhh-secret" not in log_text
    assert "service-secret" not in log_text
    assert "<SUGARKUBE_TOKEN_DEV_REDACTED>" in log_text
    assert "<SERVICE_KEY_REDACTED>" in log_text
    assert "8.8.8.8" not in log_text
    assert "<REDACTED_IP>" in log_text
    assert "192.168.5.6" in log_text
