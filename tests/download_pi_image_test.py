import hashlib
import json
import os
import subprocess
from pathlib import Path


def write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def build_release_payload(image_name: str, image_url: str, checksum_url: str) -> dict:
    return {
        "tag_name": "v1.2.3",
        "assets": [
            {"name": image_name, "browser_download_url": image_url},
            {"name": f"{image_name}.sha256", "browser_download_url": checksum_url},
        ],
    }


def setup_fake_tools(tmp_path: Path, release_payload: dict) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    release_file = tmp_path / "release.json"
    release_file.write_text(json.dumps(release_payload))

    gh = fake_bin / "gh"
    write_executable(
        gh,
        """#!/bin/bash
set -e
if [ "$1" = auth ] && [ "$2" = status ]; then
  exit ${GH_AUTH_STATUS:-1}
elif [ "$1" = auth ] && [ "$2" = token ]; then
  if [ "${GH_AUTH_STATUS:-1}" -eq 0 ]; then
    echo "${GH_AUTH_TOKEN:-}"
    exit 0
  fi
  exit 1
elif [ "$1" = api ]; then
  if [ "${GH_API_FAIL:-0}" -ne 0 ]; then
    exit 1
  fi
  repo="${GH_REPO:-futuroptimist/sugarkube}"
  if [ "$2" = "repos/$repo/releases/latest" ]; then
    cat "${GH_RELEASE_FILE:?}"
    exit 0
  fi
  if [[ "$2" == repos/*/releases/tags/* ]]; then
    cat "${GH_RELEASE_FILE:?}"
    exit 0
  fi
fi
>&2 echo "unexpected gh args: $@"
exit 1
""",
    )

    curl = fake_bin / "curl"
    write_executable(
        curl,
        """#!/bin/bash
set -euo pipefail
output=""
url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output|-o)
      shift
      output="$1"
      shift
      ;;
    --retry|--retry-delay|--continue-at)
      shift
      shift
      ;;
    -H)
      shift
      shift
      ;;
    --fail|--location|--progress-bar)
      shift
      ;;
    -* )
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done

if [[ -z "$output" || -z "$url" ]]; then
  >&2 echo "curl stub missing output or url"
  exit 1
fi

if [[ "$url" == *".sha256" ]]; then
  cp "${SHA_SRC:?}" "$output"
else
  cp "${IMG_SRC:?}" "$output"
fi
""",
    )

    return fake_bin


def run_script(tmp_path: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "download_pi_image.sh"
    return subprocess.run(
        ["/bin/bash", str(script), *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def run_wrapper(tmp_path: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    base = Path(__file__).resolve().parents[1]
    script = base / "scripts" / "sugarkube-latest.sh"
    return subprocess.run(
        ["/bin/bash", str(script), *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


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


def test_downloads_release_asset(tmp_path):
    image_name = "sugarkube.img.xz"
    image_bytes = b"pi-image"
    digest = hashlib.sha256(image_bytes).hexdigest()

    img_src = tmp_path / "source.img.xz"
    img_src.write_bytes(image_bytes)

    sha_src = tmp_path / "source.img.xz.sha256"
    sha_src.write_text(f"{digest}  {image_name}\n")

    release_payload = build_release_payload(
        image_name,
        "https://example.com/sugarkube.img.xz",
        "https://example.com/sugarkube.img.xz.sha256",
    )

    fake_bin = setup_fake_tools(tmp_path, release_payload)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GH_RELEASE_FILE": str(tmp_path / "release.json"),
            "SHA_SRC": str(sha_src),
            "IMG_SRC": str(img_src),
            "HOME": str(tmp_path),
            "GH_AUTH_STATUS": "1",
        }
    )

    output = tmp_path / "downloads" / "custom.img.xz"
    result = run_script(tmp_path, env, str(output))

    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert output.read_bytes() == image_bytes

    checksum_file = output.with_suffix(output.suffix + ".sha256")
    assert checksum_file.exists()
    assert checksum_file.read_text().strip() == f"{digest}  {output.name}"


def test_uses_default_directory(tmp_path):
    image_name = "sugarkube.img.xz"
    image_bytes = b"pi-image"
    digest = hashlib.sha256(image_bytes).hexdigest()

    img_src = tmp_path / "source.img.xz"
    img_src.write_bytes(image_bytes)

    sha_src = tmp_path / "source.img.xz.sha256"
    sha_src.write_text(f"{digest}  {image_name}\n")

    release_payload = build_release_payload(
        image_name,
        "https://example.com/sugarkube.img.xz",
        "https://example.com/sugarkube.img.xz.sha256",
    )

    fake_bin = setup_fake_tools(tmp_path, release_payload)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GH_RELEASE_FILE": str(tmp_path / "release.json"),
            "SHA_SRC": str(sha_src),
            "IMG_SRC": str(img_src),
            "HOME": str(tmp_path),
            "GH_AUTH_STATUS": "1",
        }
    )

    result = run_script(tmp_path, env)

    assert result.returncode == 0, result.stderr
    default_dir = tmp_path / "sugarkube" / "images"
    image_path = default_dir / image_name
    assert image_path.exists()
    checksum_text = (image_path.parent / f"{image_name}.sha256").read_text().strip()
    assert checksum_text == f"{digest}  {image_name}"


def test_errors_when_release_missing(tmp_path):
    release_payload = build_release_payload(
        "sugarkube.img.xz",
        "https://example.com/sugarkube.img.xz",
        "https://example.com/sugarkube.img.xz.sha256",
    )
    fake_bin = setup_fake_tools(tmp_path, release_payload)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GH_RELEASE_FILE": str(tmp_path / "release.json"),
            "SHA_SRC": str(tmp_path / "missing"),
            "IMG_SRC": str(tmp_path / "missing"),
            "GH_API_FAIL": "1",
            "GH_AUTH_STATUS": "1",
        }
    )

    result = run_script(tmp_path, env)
    assert result.returncode != 0
    assert "no published releases" in result.stderr


def test_fails_on_checksum_mismatch(tmp_path):
    image_name = "sugarkube.img.xz"
    img_src = tmp_path / "source.img.xz"
    img_src.write_bytes(b"pi-image")

    sha_src = tmp_path / "source.img.xz.sha256"
    sha_src.write_text("0000  sugarkube.img.xz\n")

    release_payload = build_release_payload(
        image_name,
        "https://example.com/sugarkube.img.xz",
        "https://example.com/sugarkube.img.xz.sha256",
    )

    fake_bin = setup_fake_tools(tmp_path, release_payload)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GH_RELEASE_FILE": str(tmp_path / "release.json"),
            "SHA_SRC": str(sha_src),
            "IMG_SRC": str(img_src),
            "HOME": str(tmp_path),
            "GH_AUTH_STATUS": "1",
        }
    )

    result = run_script(tmp_path, env)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


def test_sugarkube_latest_wrapper(tmp_path):
    image_name = "sugarkube.img.xz"
    image_bytes = b"pi-image"
    digest = hashlib.sha256(image_bytes).hexdigest()

    img_src = tmp_path / "source.img.xz"
    img_src.write_bytes(image_bytes)

    sha_src = tmp_path / "source.img.xz.sha256"
    sha_src.write_text(f"{digest}  {image_name}\n")

    release_payload = build_release_payload(
        image_name,
        "https://example.com/sugarkube.img.xz",
        "https://example.com/sugarkube.img.xz.sha256",
    )

    fake_bin = setup_fake_tools(tmp_path, release_payload)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "GH_RELEASE_FILE": str(tmp_path / "release.json"),
            "SHA_SRC": str(sha_src),
            "IMG_SRC": str(img_src),
            "HOME": str(tmp_path),
            "GH_AUTH_STATUS": "1",
        }
    )

    result = run_wrapper(tmp_path, env)

    assert result.returncode == 0, result.stderr
    default_dir = tmp_path / "sugarkube" / "images"
    image_path = default_dir / image_name
    assert image_path.exists()
