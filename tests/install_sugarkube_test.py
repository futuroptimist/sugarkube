import hashlib
import lzma
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BASE_DIR / "scripts" / "install_sugarkube.sh"


def create_gh_stub(bin_dir: Path, image: Path, checksum: Path) -> None:
    script = bin_dir / "gh"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -lt 2 ]; then
  echo "gh stub expected subcommands" >&2
  exit 1
fi
sub1="$1"
sub2="$2"
shift 2
if [ "$sub1 $sub2" = "release download" ]; then
  dir=""
  declare -a patterns
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dir)
        dir="$2"
        shift 2
        ;;
      --pattern)
        patterns+=("$2")
        shift 2
        ;;
      --repo|--tag)
        shift 2
        ;;
      --clobber)
        shift
        ;;
      *)
        shift
        ;;
    esac
  done
  if [ -z "$dir" ]; then
    echo "release download missing --dir" >&2
    exit 1
  fi
  mkdir -p "$dir"
  for pattern in "${{patterns[@]}}"; do
    case "$pattern" in
      *.sha256)
        cp "{checksum}" "$dir/$pattern"
        ;;
      *)
        cp "{image}" "$dir/$pattern"
        ;;
    esac
  done
  exit 0
fi

echo "unexpected gh stub invocation: $sub1 $sub2" >&2
exit 1
"""
    )
    script.chmod(0o755)


def run_installer(tmp_path: Path, args=None, env=None):
    cmd = ["/bin/bash", str(SCRIPT)]
    if args:
        cmd.extend(args)
    return subprocess.run(
        cmd,
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def prepare_environment(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    raw_image = b"test pi image contents"
    compressed = lzma.compress(raw_image, format=lzma.FORMAT_XZ)
    image_file = tmp_path / "sugarkube.img.xz"
    image_file.write_bytes(compressed)
    checksum_file = tmp_path / "sugarkube.img.xz.sha256"
    checksum_file.write_text(f"{hashlib.sha256(compressed).hexdigest()}  sugarkube.img.xz\n")

    create_gh_stub(fake_bin, image_file, checksum_file)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["SUGARKUBE_INSTALL_SKIP_DEPS"] = "1"
    env["HOME"] = str(tmp_path / "home")
    env["LC_ALL"] = "C"

    return env, raw_image


def test_installer_expands_latest_release(tmp_path):
    env, raw_image = prepare_environment(tmp_path)
    result = run_installer(tmp_path, env=env)
    assert result.returncode == 0, result.stderr

    dest_img = Path(env["HOME"]) / "sugarkube" / "images" / "sugarkube.img"
    assert dest_img.exists()
    assert dest_img.read_bytes() == raw_image


def test_installer_respects_custom_dir_and_keep(tmp_path):
    env, raw_image = prepare_environment(tmp_path)
    dest_dir = tmp_path / "artifacts"
    result = run_installer(
        tmp_path,
        args=["--dir", str(dest_dir), "--keep-xz", "--force"],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    expanded = dest_dir / "sugarkube.img"
    compressed = dest_dir / "sugarkube.img.xz"
    checksum = dest_dir / "sugarkube.img.xz.sha256"
    assert expanded.read_bytes() == raw_image
    assert compressed.exists()
    assert checksum.exists()
