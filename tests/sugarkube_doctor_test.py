import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def test_doctor_dry_run(tmp_path):
    download_stub = tmp_path / "download.sh"
    download_stub.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
seen_dry=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      seen_dry=1
      shift
      ;;
    --dir)
      shift 2 || true
      ;;
    *)
      shift || true
      ;;
  esac
done
if [ "$seen_dry" -ne 1 ]; then
  echo "expected --dry-run" >&2
  exit 1
fi
exit 0
"""
    )
    download_stub.chmod(0o755)

    env = os.environ.copy()
    env["SUGARKUBE_DOCTOR_DOWNLOAD"] = str(download_stub)
    env["SUGARKUBE_DOCTOR_SKIP_LINT"] = "1"
    env["SUGARKUBE_REPORT_DIR"] = str(tmp_path / "reports")

    result = subprocess.run(
        ["/bin/bash", str(BASE_DIR / "scripts" / "sugarkube_doctor.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Doctor finished" in result.stdout
    reports = list((tmp_path / "reports").glob("*.md"))
    assert reports, "expected report markdown"
