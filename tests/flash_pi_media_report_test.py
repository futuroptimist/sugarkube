import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import flash_pi_media as flash
from scripts import flash_pi_media_report as report

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


def test_run_flash_forwards_cloud_init(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, list[str]] = {}

    def fake_main(argv: list[str]) -> int:
        recorded["argv"] = argv
        return 0

    monkeypatch.setattr(report.flash, "main", fake_main)

    args = SimpleNamespace(
        no_eject=False,
        keep_mounted=False,
        dry_run=False,
        cloud_init="override.yaml",
    )
    device = flash.Device(path="/dev/sdz", description="disk", size=0, is_removable=True)

    stdout, stderr, expected, verified = report._run_flash(Path("image.img"), args, device)

    assert recorded["argv"].count("--cloud-init") == 1
    assert "override.yaml" in recorded["argv"]
