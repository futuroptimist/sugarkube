import json
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def create_gh_stub(bin_dir: Path) -> None:
    script = bin_dir / "gh"
    script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command="${1:-}"
shift || true
case "$command" in
  api)
    if [ -n "${GH_RELEASE_PAYLOAD:-}" ]; then
      printf '%s' "$GH_RELEASE_PAYLOAD"
      exit 0
    fi
    exit 1
    ;;
  auth)
    if [ "${1:-}" = token ]; then
      echo "stub-token"
      exit 0
    fi
    ;;
  run)
    if [ "${1:-}" = list ]; then
      echo "12345"
      exit 0
    fi
    ;;
 esac
 echo "unexpected gh invocation" >&2
 exit 1
"""
    )
    script.chmod(0o755)


def _release_payload() -> str:
    return json.dumps(
        {
            "tag_name": "v0.0.0",
            "assets": [
                {
                    "name": "sugarkube.img.xz",
                    "browser_download_url": "file:///tmp/sugarkube.img.xz",
                },
                {
                    "name": "sugarkube.img.xz.sha256",
                    "browser_download_url": "file:///tmp/sugarkube.img.xz.sha256",
                },
            ],
        }
    )


def test_doctor_skip_checks(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    create_gh_stub(fake_bin)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(tmp_path / "home")
    env["GH_RELEASE_PAYLOAD"] = _release_payload()

    result = subprocess.run(
        ["/bin/bash", str(BASE_DIR / "scripts" / "doctor.sh"), "--skip-checks"],
        capture_output=True,
        text=True,
        env=env,
        cwd=BASE_DIR,
    )

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    report_path = Path(lines[-1])
    assert report_path.exists()
    content = report_path.read_text()
    assert "Sugarkube Flash Report" in content
    assert "cloud-init" in content
