import lzma
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def _doctor_env(env: dict) -> dict:
    result = env.copy()
    result["SUGARKUBE_FLASH_ALLOW_NONROOT"] = "1"
    return result


def test_flash_imgxz_to_regular_file(tmp_path):
    content = b"sugarkube" * 2048
    img, archive = make_image(tmp_path, content)
    device = tmp_path / "device.bin"
    device.touch()

    env = _doctor_env(os.environ)

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


def test_generates_markdown_report(tmp_path):
    content = b"report" * 2048
    _, archive = make_image(tmp_path, content)
    device = tmp_path / "report-device.bin"
    device.touch()

    baseline = tmp_path / "baseline.yaml"
    override = tmp_path / "override.yaml"
    baseline.write_text("hostname: sugarkube\n")
    override.write_text("hostname: sugarkube-updated\nssh_authorized_keys: []\n")
    report = tmp_path / "flash.md"

    env = _doctor_env(os.environ)

    result = run_flash(
        [
            "--image",
            str(archive),
            "--device",
            str(device),
            "--assume-yes",
            "--keep-mounted",
            "--no-eject",
            "--report",
            str(report),
            "--report-format",
            "markdown",
            "--cloud-init-baseline",
            str(baseline),
            "--cloud-init-user-data",
            str(override),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    text = report.read_text()
    assert "Sugarkube Flash Report" in text
    assert "cloud-init diff" in text
    assert "hostname: sugarkube" in text
    assert "hostname: sugarkube-updated" in text
    assert "Expected SHA-256" in text


def test_generates_html_report(tmp_path):
    content = b"html" * 1024
    _, archive = make_image(tmp_path, content)
    device = tmp_path / "html-device.bin"
    device.touch()

    baseline = tmp_path / "base.yaml"
    override = tmp_path / "override.yaml"
    baseline.write_text("timezone: UTC\n")
    override.write_text("timezone: Europe/Paris\n")
    report = tmp_path / "flash.html"

    env = _doctor_env(os.environ)

    result = run_flash(
        [
            "--image",
            str(archive),
            "--device",
            str(device),
            "--assume-yes",
            "--keep-mounted",
            "--no-eject",
            "--report",
            str(report),
            "--report-format",
            "html",
            "--cloud-init-baseline",
            str(baseline),
            "--cloud-init-user-data",
            str(override),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    html_body = report.read_text()
    assert "<!DOCTYPE html>" in html_body
    assert "cloud-init diff" in html_body
    assert "Europe/Paris" in html_body
