from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "lib" / "capture_debug_log.py"


def _run_capture(
    tmp_path: Path, log_path: Path, payload: str, mask_values: list[str] | None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if mask_values is not None:
        mask_file = tmp_path / "mask.txt"
        mask_file.write_text("\n".join(mask_values), encoding="utf-8")
        env["SUGARKUBE_DEBUG_MASK_FILE"] = str(mask_file)
    else:
        env.pop("SUGARKUBE_DEBUG_MASK_FILE", None)
    return subprocess.run(
        [str(SCRIPT), str(log_path)],
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )


def test_capture_masks_tokens_and_external_ips(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "capture.log"
    sample_secret = "K10abc123"
    external_ip = "8.8.8.8"
    internal_ip = "10.0.0.5"
    ipv6 = "2001:db8::1"
    payload = (
        f"token {sample_secret}\nexternal {external_ip}\ninternal {internal_ip}\nipv6 {ipv6}\n"
    )

    result = _run_capture(tmp_path, log_path, payload, [sample_secret])

    output = log_path.read_text(encoding="utf-8")
    assert sample_secret not in output
    assert "<REDACTED>" in output
    assert external_ip not in output
    assert "<REDACTED_IP>" in output
    assert internal_ip in output
    assert ipv6 not in output
    assert "<REDACTED_IP>" in result.stdout


def test_capture_creates_parent_directories(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "debug.log"
    _run_capture(tmp_path, log_path, "hello world\n", None)
    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8").strip() == "hello world"
