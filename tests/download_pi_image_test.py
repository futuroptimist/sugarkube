import os
import subprocess
from pathlib import Path

from tests.download_test_utils import download_script_path, write_stub_scripts


def test_requires_gh(tmp_path):
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(download_script_path())],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "gh is required" in result.stderr


def test_downloads_and_verifies_artifact(tmp_path):
    env = write_stub_scripts(tmp_path)
    out = tmp_path / "out" / "sugarkube.img.xz"
    result = subprocess.run(
        ["/bin/bash", str(download_script_path()), "-o", str(out)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    checksum = Path(str(out) + ".sha256")
    assert checksum.exists()


def test_errors_when_download_fails(tmp_path):
    env = write_stub_scripts(tmp_path)
    env["BLOCK_IMAGE_DOWNLOAD"] = "1"
    env["FAIL_IMAGE_DOWNLOAD"] = "55"
    out = tmp_path / "fail.img.xz"
    result = subprocess.run(
        ["/bin/bash", str(download_script_path()), "-o", str(out)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not out.exists()


def test_errors_when_asset_missing(tmp_path):
    env = write_stub_scripts(tmp_path, asset_name="other.img")
    out = tmp_path / "missing.img.xz"
    result = subprocess.run(
        ["/bin/bash", str(download_script_path()), "-o", str(out)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "asset" in result.stderr


def test_uses_default_output_directory(tmp_path):
    env = write_stub_scripts(tmp_path)
    home = tmp_path / "home"
    env["HOME"] = str(home)
    result = subprocess.run(
        ["/bin/bash", str(download_script_path())],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    default_path = home / "sugarkube" / "images" / "sugarkube.img.xz"
    assert default_path.exists()


def test_skips_download_when_existing_file_verifies(tmp_path):
    env = write_stub_scripts(tmp_path)
    marker = tmp_path / "marker.txt"
    env["IMAGE_MARKER"] = str(marker)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    target = output_dir / "sugarkube.img.xz"
    target.write_bytes(Path(env["IMAGE_SOURCE"]).read_bytes())
    sha_path = Path(str(target) + ".sha256")
    sha_path.write_text(Path(env["SHA_SOURCE"]).read_text())

    env["BLOCK_IMAGE_DOWNLOAD"] = "1"
    env["FAIL_IMAGE_DOWNLOAD"] = "77"

    result = subprocess.run(
        ["/bin/bash", str(download_script_path()), "-o", str(target)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert not marker.exists()


def test_allows_missing_checksum(tmp_path):
    env = write_stub_scripts(tmp_path, include_checksum=False)
    out = tmp_path / "no-checksum.img.xz"
    result = subprocess.run(
        ["/bin/bash", str(download_script_path()), "-o", str(out)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert out.exists()
    assert not Path(str(out) + ".sha256").exists()
