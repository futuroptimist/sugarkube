import os
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
