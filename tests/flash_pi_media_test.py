import contextlib
import lzma
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import flash_pi_media as flash

BASE_DIR = Path(__file__).resolve().parents[1]


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


def test_cloud_init_override_copies_user_data(tmp_path, monkeypatch):
    content = b"override" * 2048
    img, archive = make_image(tmp_path, content)
    device = tmp_path / "device.bin"
    device.touch()

    env = os.environ.copy()
    env["SUGARKUBE_FLASH_ALLOW_NONROOT"] = "1"

    override = tmp_path / "user-data.yaml"
    override.write_text("hostname: sugarkube\n", encoding="utf-8")

    mount_dir = tmp_path / "boot"
    mount_dir.mkdir()

    monkeypatch.setattr(
        flash,
        "_resolve_boot_partition",
        lambda _device: flash.BootPartition(path="/dev/mock", mountpoint=str(mount_dir)),
    )

    @contextlib.contextmanager
    def fake_mount(partition):
        yield Path(partition.mountpoint)

    monkeypatch.setattr(flash, "_mount_boot_partition", fake_mount)

    result = run_flash(
        [
            "--image",
            str(archive),
            "--device",
            str(device),
            "--assume-yes",
            "--no-eject",
            "--cloud-init",
            str(override),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    expected_override = override.read_text(encoding="utf-8")
    assert (mount_dir / "user-data").read_text(encoding="utf-8") == expected_override
    assert "Copied cloud-init override" in result.stdout


def test_cloud_init_missing_file_errors(tmp_path):
    content = b"data" * 2048
    img, archive = make_image(tmp_path, content)
    device = tmp_path / "device.raw"
    device.touch()

    env = os.environ.copy()
    env["SUGARKUBE_FLASH_ALLOW_NONROOT"] = "1"

    missing = tmp_path / "missing.yaml"

    result = run_flash(
        [
            "--image",
            str(archive),
            "--device",
            str(device),
            "--assume-yes",
            "--no-eject",
            "--cloud-init",
            str(missing),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "Cloud-init override not found" in result.stderr
