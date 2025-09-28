import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BASE_DIR / "scripts" / "flash_pi_media_report.py"


def run_report(args: list[str]):
    cmd = [sys.executable, str(SCRIPT)] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def test_list_devices_without_image_exits_cleanly():
    result = run_report(["--list-devices"])
    assert result.returncode == 0, result.stderr
    assert "Provide --image" not in result.stderr
    assert "No removable drives detected" in result.stdout or "Device" in result.stdout
