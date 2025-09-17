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


def test_flash_report_outputs_markdown_and_html(tmp_path):
    content = b"report" * 4096
    _, archive = make_image(tmp_path, content)
    device = tmp_path / "device.bin"
    device.touch()

    baseline = (BASE_DIR / "scripts" / "cloud-init" / "user-data.yaml").read_text(encoding="utf-8")
    override = tmp_path / "user-data.override.yaml"
    override.write_text(baseline + "\n# test override\n", encoding="utf-8")

    report_dir = tmp_path / "reports"
    env = os.environ.copy()
    env["SUGARKUBE_FLASH_ALLOW_NONROOT"] = "1"
    env["SUGARKUBE_REPORT_DIR"] = str(report_dir)

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
            "--cloud-init-override",
            str(override),
        ],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    reports = sorted(report_dir.glob("flash-*.md"))
    assert reports, "expected markdown report"
    md_path = reports[-1]
    html_path = md_path.with_suffix(".html")
    assert html_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "Sugarkube Flash Report" in md_text
    assert "test override" in md_text
