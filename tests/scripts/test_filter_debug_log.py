from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "filter_debug_log.py"


@pytest.mark.parametrize(
    "input_text,expected_fragment",
    [
        ("status ok\n", "status ok"),
        ("external 8.8.8.8 internal 192.168.1.9\n", "external [REDACTED_IP] internal 192.168.1.9"),
    ],
)
def test_filter_writes_sanitized_content(tmp_path: Path, input_text: str, expected_fragment: str) -> None:
    log_path = tmp_path / "run.log"
    env = os.environ.copy()
    env.update({"TEST_SECRET_TOKEN": "PLACEHOLDER"})
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log_path)],
        input=input_text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )

    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert expected_fragment in log_text
    # The console output should stay unmodified
    assert input_text == result.stdout.decode("utf-8")


def test_filter_redacts_secrets_in_log(tmp_path: Path) -> None:
    log_path = tmp_path / "run.log"
    env = os.environ.copy()
    env.update({"SUGARKUBE_TOKEN_DEV": "my-secret-token"})
    payload = "token my-secret-token still prints to console\n"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log_path)],
        input=payload.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )

    console = result.stdout.decode("utf-8")
    assert "my-secret-token" in console

    sanitized = log_path.read_text(encoding="utf-8")
    assert "my-secret-token" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized
