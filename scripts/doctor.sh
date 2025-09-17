#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

err() {
  printf 'ERROR: %s\n' "$*" >&2
}

die() {
  err "$1"
  exit "${2:-1}"
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s' "python"
    return 0
  fi
  die "python3 (or python) is required for doctor checks"
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

DOWNLOAD_ARGS=()
FLASH_ARGS=()

usage() {
  cat <<'USAGE'
Run a fast health check covering release availability, flash dry-run, and linting.

Usage: doctor.sh [options]

Options:
      --download-arg ARG   Forward an extra argument to download_pi_image.sh
                           (can be repeated)
      --flash-arg ARG      Forward an extra argument to flash_pi_media.py
                           (can be repeated)
      --skip-checks        Skip scripts/checks.sh (lint/test) stage
  -h, --help               Show this message

Environment:
  SUGARKUBE_DOCTOR_SKIP_CHECKS=1  Skip the lint/test stage without flags
USAGE
}

SKIP_CHECKS=${SUGARKUBE_DOCTOR_SKIP_CHECKS:-0}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --download-arg)
      if [ "$#" -lt 2 ]; then
        die "--download-arg requires a value"
      fi
      DOWNLOAD_ARGS+=("$2")
      shift 2
      ;;
    --flash-arg)
      if [ "$#" -lt 2 ]; then
        die "--flash-arg requires a value"
      fi
      FLASH_ARGS+=("$2")
      shift 2
      ;;
    --skip-checks)
      SKIP_CHECKS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

PYTHON_BIN=$(find_python)

tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
report_dir_default="${HOME:-$tmp_dir}/sugarkube/reports"
report_root="${SUGARKUBE_DOCTOR_REPORT_DIR:-$report_dir_default}"
final_report="$report_root/flash-report-${timestamp}.md"

log "Checking latest release availability (dry-run)"
"$SCRIPT_DIR/download_pi_image.sh" --dry-run "${DOWNLOAD_ARGS[@]}"

image_path="$tmp_dir/sugarkube-doctor.img"
archive_path="${image_path}.xz"
device_path="$tmp_dir/flash-device.bin"
report_path="$tmp_dir/flash-report.md"
cloud_baseline="$tmp_dir/cloud-init-baseline.yaml"
cloud_override="$tmp_dir/cloud-init-override.yaml"

log "Preparing sample image for flash dry-run"
IMAGE_OUTPUT="$image_path" ARCHIVE_OUTPUT="$archive_path" "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import lzma
import os

image = Path(os.environ["IMAGE_OUTPUT"])
archive = Path(os.environ["ARCHIVE_OUTPUT"])
data = (b"sugarkube-doctor" * 1024)
image.write_bytes(data)
with lzma.open(archive, "wb") as fh:
    fh.write(data)
PY

log "Creating cloud-init baseline snapshot"
if [ -f "$SCRIPT_DIR/cloud-init/user-data.yaml" ]; then
  cp "$SCRIPT_DIR/cloud-init/user-data.yaml" "$cloud_baseline"
else
  printf 'hostname: sugarkube\n' >"$cloud_baseline"
fi

log "Generating cloud-init override"
cat <<'YAML' >"$cloud_override"
hostname: sugarkube-doctor
users:
  - name: pi
    groups: sudo
    shell: /bin/bash
YAML

log "Running flash dry-run to regular file"
: >"$device_path"
SUGARKUBE_FLASH_ALLOW_NONROOT=1 "$PYTHON_BIN" "$SCRIPT_DIR/flash_pi_media.py" \
  --image "$archive_path" \
  --device "$device_path" \
  --assume-yes \
  --keep-mounted \
  --no-eject \
  --report "$report_path" \
  --report-format markdown \
  --cloud-init-baseline "$cloud_baseline" \
  --cloud-init-user-data "$cloud_override" \
  "${FLASH_ARGS[@]}"

if [ "$SKIP_CHECKS" -ne 1 ]; then
  log "Running repository lint/test checks"
  (cd "$REPO_ROOT" && "$SCRIPT_DIR/checks.sh")
else
  log "Skipping lint/test checks (requested)"
fi

mkdir -p "$report_root"
cp "$report_path" "$final_report"

log "Doctor finished. Flash report stored at $final_report"
printf '%s\n' "$final_report"
