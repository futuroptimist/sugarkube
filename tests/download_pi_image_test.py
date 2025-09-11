import os
import shutil
import subprocess
from pathlib import Path


def test_requires_gh(tmp_path):
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "gh is required" in result.stderr


def test_downloads_artifact(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    src = tmp_path / "src.img.xz"
    src.write_text("data")
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  echo 42\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        "  shift 2\n"
        '  while [ "$1" != --dir ]; do shift; done\n'
        "  dir=$2\n"
        '  cp "$GH_SRC" "$dir/sugarkube.img.xz"\n'
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GH_SRC"] = str(src)
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script), "out.img.xz"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert (tmp_path / "out.img.xz").exists()


def test_errors_when_download_fails(tmp_path):
    """The script should fail if the artifact download step errors."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  echo 42\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        "  exit 1\n"
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script), "out.img.xz"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "out.img.xz").exists()


def test_errors_when_no_run_found(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "download_called"
    gh = fake_bin / "gh"
    gh.write_text(
        f"#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  exit 0\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        f"  echo called > {marker}\n"
        "  exit 0\n"
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "no pi-image workflow runs found" in result.stderr
    assert not marker.exists()


def test_uses_default_output(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    src = tmp_path / "src.img.xz"
    src.write_text("data")
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  echo 42\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        "  shift 2\n"
        '  while [ "$1" != --dir ]; do shift; done\n'
        "  dir=$2\n"
        '  cp "$GH_SRC" "$dir/sugarkube.img.xz"\n'
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GH_SRC"] = str(src)
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert (tmp_path / "sugarkube.img.xz").exists()


def test_creates_output_directory(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    src = tmp_path / "src.img.xz"
    src.write_text("data")
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  echo 42\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        "  shift 2\n"
        '  while [ "$1" != --dir ]; do shift; done\n'
        "  dir=$2\n"
        '  cp "$GH_SRC" "$dir/sugarkube.img.xz"\n'
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GH_SRC"] = str(src)
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    out = tmp_path / "nested" / "out.img.xz"
    result = subprocess.run(
        ["/bin/bash", str(script), str(out)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert out.exists()
    assert (tmp_path / "nested").is_dir()


def test_downloads_without_realpath(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    src = tmp_path / "src.img.xz"
    src.write_text("data")
    sha = tmp_path / "src.img.xz.sha256"
    sha.write_text("sum  sugarkube.img.xz\n")

    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  echo 42\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        "  shift 2\n"
        '  while [ "$1" != --dir ]; do shift; done\n'
        "  dir=$2\n"
        '  cp "$GH_SRC" "$dir/sugarkube.img.xz"\n'
        '  cp "$GH_SHA" "$dir/sugarkube.img.xz.sha256"\n'
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    # Symlink required utilities but omit realpath
    for cmd in ["dirname", "mkdir", "mv", "ls", "cp"]:
        target = shutil.which(cmd)
        assert target is not None
        (fake_bin / cmd).symlink_to(target)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin)
    env["GH_SRC"] = str(src)
    env["GH_SHA"] = str(sha)

    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script), "out.img.xz"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert (tmp_path / "out.img.xz").exists()
    assert (tmp_path / "out.img.xz.sha256").exists()


def test_overwrites_existing_output_and_checksum(tmp_path):
    """Existing files should be replaced when downloading a new image."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    src = tmp_path / "src.img.xz"
    src.write_text("fresh")
    sha = tmp_path / "src.img.xz.sha256"
    sha.write_text("newsha  sugarkube.img.xz\n")

    gh = fake_bin / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = run ] && [ "$2" = list ]; then\n'
        "  echo 42\n"
        'elif [ "$1" = run ] && [ "$2" = download ]; then\n'
        "  shift 2\n"
        '  while [ "$1" != --dir ]; do shift; done\n'
        "  dir=$2\n"
        '  cp "$GH_SRC" "$dir/sugarkube.img.xz"\n'
        '  cp "$GH_SHA" "$dir/sugarkube.img.xz.sha256"\n'
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    gh.chmod(0o755)

    out = tmp_path / "out.img.xz"
    out.write_text("stale")
    out_sha = tmp_path / "out.img.xz.sha256"
    out_sha.write_text("oldsha  out.img.xz\n")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GH_SRC"] = str(src)
    env["GH_SHA"] = str(sha)

    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    result = subprocess.run(
        ["/bin/bash", str(script), str(out)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text() == "fresh"
    assert out_sha.read_text() == "newsha  sugarkube.img.xz\n"
