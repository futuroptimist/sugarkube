import hashlib
import json
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def run_script(script_name, args=None, env=None, cwd=None):
    cmd = ["/bin/bash", str(BASE_DIR / "scripts" / script_name)]
    if args:
        cmd.extend(args)
    return subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)


def create_gh_stub(bin_dir: Path) -> None:
    script = bin_dir / "gh"
    script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
cmd="${1:-}"
if [ $# -gt 0 ]; then
  shift
fi
if [ -n "${GH_DEBUG_FILE:-}" ]; then
  {
    printf '%s %s\n' "$cmd" "$*"
    printf 'payload=%s\n' "${GH_RELEASE_PAYLOAD:-<unset>}"
  } >>"$GH_DEBUG_FILE"
fi
case "$cmd" in
  api)
    if [ -n "${GH_RELEASE_PAYLOAD:-}" ]; then
      printf '%s' "$GH_RELEASE_PAYLOAD"
      exit 0
    fi
    exit 1
    ;;
  run)
    sub="${1:-}"
    if [ $# -gt 0 ]; then
      shift
    fi
    case "$sub" in
      list)
        echo "${GH_RUN_ID:-4242}"
        exit 0
        ;;
      download)
        output_dir=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --dir)
              output_dir="$2"
              shift 2 || true
              ;;
            *)
              shift || true
              ;;
          esac
        done
        if [ -z "$output_dir" ]; then
          echo "missing --dir" >&2
          exit 1
        fi
        if [ -n "${GH_WORKFLOW_IMAGE:-}" ]; then
          cp "$GH_WORKFLOW_IMAGE" "$output_dir/sugarkube.img.xz"
        fi
        if [ -n "${GH_WORKFLOW_SHA:-}" ]; then
          cp "$GH_WORKFLOW_SHA" "$output_dir/sugarkube.img.xz.sha256"
        fi
        exit 0
        ;;
    esac
    ;;
  auth)
    sub="${1:-}"
    if [ "$sub" = token ] && [ -n "${GH_TOKEN:-}" ]; then
      echo "$GH_TOKEN"
      exit 0
    fi
    ;;
esac

echo "unexpected gh call: $cmd $*" >&2
exit 1
"""
    )
    script.chmod(0o755)


def _base_env(tmp_path, fake_bin):
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GH_TOKEN"] = "dummy-token"
    env["GITHUB_TOKEN"] = "dummy-token"
    return env


def _release_payload(image: Path, checksum: Path) -> str:
    return json.dumps(
        {
            "tag_name": "v1.2.3",
            "assets": [
                {
                    "name": "sugarkube.img.xz",
                    "browser_download_url": f"file://{image}",
                },
                {
                    "name": "sugarkube.img.xz.sha256",
                    "browser_download_url": f"file://{checksum}",
                },
            ],
        }
    )


def test_requires_gh(tmp_path):
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    result = run_script("download_pi_image.sh", env=env, cwd=tmp_path)
    assert result.returncode != 0
    assert "gh is required" in result.stderr


def test_downloads_release_asset(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    payload = b"sugarkube"
    release_img = tmp_path / "release.img.xz"
    release_img.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    release_sha = tmp_path / "release.img.xz.sha256"
    release_sha.write_text(f"{sha}\n")

    env = _base_env(tmp_path, fake_bin)
    env["HOME"] = str(tmp_path / "home")
    env["GH_RELEASE_PAYLOAD"] = _release_payload(release_img, release_sha)

    result = run_script("download_pi_image.sh", env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    dest = Path(env["HOME"]) / "sugarkube" / "images" / "sugarkube.img.xz"
    checksum = Path(str(dest) + ".sha256")
    assert dest.read_bytes() == payload
    assert checksum.read_text().strip() == sha
    assert "Checksum verified" in result.stdout


def test_checksum_mismatch_errors(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    payload = b"ok"
    release_img = tmp_path / "release.img.xz"
    release_img.write_bytes(payload)
    wrong_sha = tmp_path / "release.img.xz.sha256"
    wrong_sha.write_text("deadbeef\n")

    env = _base_env(tmp_path, fake_bin)
    env["HOME"] = str(tmp_path / "home")
    env["GH_RELEASE_PAYLOAD"] = _release_payload(release_img, wrong_sha)

    result = run_script("download_pi_image.sh", env=env, cwd=tmp_path)
    assert result.returncode != 0
    assert "Checksum mismatch" in result.stderr


def test_falls_back_to_workflow_when_release_missing(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    payload = b"workflow"
    workflow_img = tmp_path / "workflow.img.xz"
    workflow_img.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    workflow_sha = tmp_path / "workflow.img.xz.sha256"
    workflow_sha.write_text(f"{sha}\n")

    env = _base_env(tmp_path, fake_bin)
    env["HOME"] = str(tmp_path / "home")
    env["GH_WORKFLOW_IMAGE"] = str(workflow_img)
    env["GH_WORKFLOW_SHA"] = str(workflow_sha)
    # No GH_RELEASE_PAYLOAD env var → triggers workflow fallback.

    result = run_script("download_pi_image.sh", env=env, cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    dest = Path(env["HOME"]) / "sugarkube" / "images" / "sugarkube.img.xz"
    checksum = Path(str(dest) + ".sha256")
    assert dest.read_bytes() == payload
    assert checksum.read_text().strip() == sha
    assert "Falling back to latest successful pi-image" in result.stdout


def test_honors_output_override(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    payload = b"override"
    release_img = tmp_path / "release.img.xz"
    release_img.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    release_sha = tmp_path / "release.img.xz.sha256"
    release_sha.write_text(f"{sha}\n")

    env = _base_env(tmp_path, fake_bin)
    env["GH_RELEASE_PAYLOAD"] = _release_payload(release_img, release_sha)

    custom_output = tmp_path / "downloads" / "custom.img.xz"
    result = run_script(
        "download_pi_image.sh",
        args=["--output", str(custom_output)],
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert custom_output.read_bytes() == payload
    checksum = Path(str(custom_output) + ".sha256")
    assert checksum.read_text().strip() == sha
