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
        '  while [ \"$1\" != --dir ]; do shift; done\n'
        "  dir=$2\n"
        '  cp \"$GH_SRC\" \"$dir/sugarkube.img.xz\"\n'
        '  cp \"$GH_SHA\" \"$dir/sugarkube.img.xz.sha256\"\n'
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
