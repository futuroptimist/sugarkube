import lzma
import os
import subprocess
from pathlib import Path

from tests.download_test_utils import latest_script_path, write_stub_scripts


def test_downloads_and_expands(tmp_path):
    env = write_stub_scripts(tmp_path)
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(latest_script_path())],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    compressed = tmp_path / "sugarkube" / "images" / "sugarkube.img.xz"
    expanded = tmp_path / "sugarkube" / "images" / "sugarkube.img"
    assert compressed.exists()
    assert expanded.exists()

    with lzma.open(compressed, "rb") as source:
        expected = source.read()
    assert expanded.read_bytes() == expected


def test_no_expand_option(tmp_path):
    env = write_stub_scripts(tmp_path)
    out_dir = tmp_path / "images"
    result = subprocess.run(
        [
            "/bin/bash",
            str(latest_script_path()),
            "-d",
            str(out_dir),
            "--no-expand",
        ],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    compressed = out_dir / "sugarkube.img.xz"
    raw = out_dir / "sugarkube.img"
    assert compressed.exists()
    assert not raw.exists()


def test_skips_expansion_when_up_to_date(tmp_path):
    env = write_stub_scripts(tmp_path)
    out_dir = tmp_path / "images"
    out_dir.mkdir()
    compressed = out_dir / "sugarkube.img.xz"
    compressed.write_bytes(Path(env["IMAGE_SOURCE"]).read_bytes())
    raw = out_dir / "sugarkube.img"
    with lzma.open(compressed, "rb") as source:
        raw.write_bytes(source.read())

    old_mtime = raw.stat().st_mtime
    # Ensure raw appears newer than compressed so expansion is skipped
    os.utime(raw, None)
    os.utime(compressed, (old_mtime - 10, old_mtime - 10))
    before = raw.stat().st_mtime

    result = subprocess.run(
        ["/bin/bash", str(latest_script_path()), "-d", str(out_dir)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    after = raw.stat().st_mtime
    assert after == before
