#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [ -n "${2:-}" ]; then
      die "$2"
    fi
    die "Missing required command: $1"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_SCRIPT="${SUGARKUBE_DOCTOR_DOWNLOAD:-$SCRIPT_DIR/download_pi_image.sh}"
FLASH_SCRIPT="${SUGARKUBE_DOCTOR_FLASH:-$SCRIPT_DIR/flash_pi_media.py}"

require_cmd python3 "python3 is required for doctor dry-run"

if [ ! -x "$DOWNLOAD_SCRIPT" ]; then
  die "Download helper not found or not executable: $DOWNLOAD_SCRIPT"
fi

if [ ! -f "$FLASH_SCRIPT" ]; then
  die "Flash helper not found: $FLASH_SCRIPT"
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

log "Checking image availability (dry-run)"
if ! "$DOWNLOAD_SCRIPT" --dir "$work_dir" --dry-run; then
  die "Download dry-run failed"
fi

log "Generating synthetic image"
mapfile -t generated < <(cd "$work_dir" && python3 - <<'PYCODE'
import lzma
import secrets
from pathlib import Path

target_dir = Path(".")
img_path = target_dir / "doctor.img"
archive_path = target_dir / "doctor.img.xz"

payload = secrets.token_bytes(1024 * 64)
img_path.write_bytes(payload)
with lzma.open(archive_path, "wb", preset=6) as fh:
    fh.write(payload)
print(img_path.resolve())
print(archive_path.resolve())
PYCODE
)

archive_path="${generated[1]:-$work_dir/doctor.img.xz}"

if [ ! -f "$archive_path" ]; then
  die "Failed to build synthetic archive"
fi

log "Running flash dry-run"
export SUGARKUBE_FLASH_ALLOW_NONROOT=1
touch "$work_dir/doctor-device.bin"
python3 "$FLASH_SCRIPT" \
  --image "$archive_path" \
  --device "$work_dir/doctor-device.bin" \
  --assume-yes --keep-mounted --no-eject \
  --report "$work_dir/doctor-report" \
  --cloud-init-override "$SCRIPT_DIR/cloud-init/user-data.yaml" >/dev/null

report_dir="${SUGARKUBE_REPORT_DIR:-$HOME/sugarkube/reports}"
report_md="$work_dir/doctor-report.md"
report_html="$work_dir/doctor-report.html"
if [ -f "$report_md" ]; then
  mkdir -p "$report_dir"
  cp "$report_md" "$report_dir/"
  if [ -f "$report_html" ]; then
    cp "$report_html" "$report_dir/"
  fi
  log "Stored flash report in $report_dir"
fi

log "Flash dry-run succeeded"

if [ "${SUGARKUBE_DOCTOR_SKIP_LINT:-0}" = "1" ]; then
  log "Skipping pre-commit lint per SUGARKUBE_DOCTOR_SKIP_LINT"
else
  require_cmd pre-commit "Install pre-commit (pipx install pre-commit) before running make doctor"
  log "Running pre-commit checks"
  pre-commit run --all-files
fi

log "Doctor finished"
