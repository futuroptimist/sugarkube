import importlib.util
import lzma
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]

MODULE_PATH = BASE_DIR / "scripts" / "flash_pi_media.py"
SPEC = importlib.util.spec_from_file_location("flash_pi_media_module", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault(SPEC.name, MODULE)
SPEC.loader.exec_module(MODULE)


def run_flash(args, env=None, cwd=None):
    cmd = [sys.executable, str(BASE_DIR / "scripts" / "flash_pi_media.py")]
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)


def make_image(tmp_path: Path, content: bytes) -> tuple[Path, Path]:
    img = tmp_path / "sugarkube.img"
    img.write_bytes(content)
    archive = img.with_suffix(".img.xz")
    with lzma.open(archive, "wb") as fh:
        fh.write(content)
    return img, archive


def test_flash_imgxz_to_regular_file(tmp_path):
    content = b"sugarkube" * 2048
    img, archive = make_image(tmp_path, content)
    device = tmp_path / "device.bin"
    device.touch()

    env = os.environ.copy()
    env["SUGARKUBE_FLASH_ALLOW_NONROOT"] = "1"

    result = run_flash(
        [
            "--image",
            str(archive),
            "--device",
            str(device),
            "--assume-yes",
            "--keep-mounted",
            "--no-eject",
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert device.read_bytes() == content
    assert "Finished writing" in result.stdout
    assert "Verified device SHA-256" in result.stdout


def test_requires_root_without_override(tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("Running as root; cannot exercise the permission check")
    content = b"data" * 512
    img, archive = make_image(tmp_path, content)
    device = tmp_path / "device.raw"
    device.touch()

    result = run_flash(
        [
            "--image",
            str(archive),
            "--device",
            str(device),
            "--assume-yes",
            "--keep-mounted",
            "--no-eject",
        ],
        env=os.environ.copy(),
    )

    assert result.returncode != 0
    assert "Run as root or with sudo" in result.stderr


def test_auto_selects_single_candidate(monkeypatch, tmp_path, capsys):
    content = b"auto" * 1024
    image = tmp_path / "input.img"
    image.write_bytes(content)

    device_path = tmp_path / "auto-device.bin"
    device_path.write_bytes(b"\0" * len(content))

    candidate = MODULE.Device(
        path=str(device_path),
        description="Test device",
        size=len(content),
        is_removable=True,
        mountpoints=(),
    )

    monkeypatch.setattr(MODULE, "discover_devices", lambda: [candidate])
    monkeypatch.setattr(MODULE, "filter_candidates", lambda devices: list(devices))

    monkeypatch.setenv("SUGARKUBE_FLASH_ALLOW_NONROOT", "1")

    exit_code = MODULE.main(
        [
            "--image",
            str(image),
            "--assume-yes",
            "--keep-mounted",
            "--no-eject",
        ]
    )

    assert exit_code == 0
    assert device_path.read_bytes() == content
    captured = capsys.readouterr()
    assert "Auto-selecting" in captured.out
