#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '==> %s\n' "$*"
}

warn() {
  printf 'warning: %s\n' "$*" >&2
}

cleanup() {
  if [ -d "${DOCTOR_TMP:-}" ]; then
    rm -rf "$DOCTOR_TMP"
  fi
}

DOCTOR_TMP="$(mktemp -d)"
trap cleanup EXIT

DOWNLOAD_LOG="$DOCTOR_TMP/download.log"
FLASH_LOG="$DOCTOR_TMP/flash.log"

log "Resolving latest sugarkube image metadata"
if ! "$SCRIPT_DIR/download_pi_image.sh" --dry-run --dir "$DOCTOR_TMP" >"$DOWNLOAD_LOG" 2>&1; then
  cat "$DOWNLOAD_LOG" >&2 || true
  exit 1
fi

log "Preparing synthetic image for flash dry-run"
DOCTOR_IMAGE="$DOCTOR_TMP/sugarkube-doctor.img"
python3 - "$DOCTOR_IMAGE" <<'PY'
import os, sys
path = sys.argv[1]
with open(path, "wb") as fh:
    fh.write(os.urandom(1024 * 1024))
PY

DOCTOR_DEVICE="$DOCTOR_TMP/sugarkube-doctor-device.bin"
python3 - "$DOCTOR_DEVICE" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_bytes(b"\0" * 1024)
PY

log "Running flash dry-run"
SUGARKUBE_FLASH_ALLOW_NONROOT=1 python3 "$SCRIPT_DIR/flash_pi_media.py" \
  --image "$DOCTOR_IMAGE" \
  --device "$DOCTOR_DEVICE" \
  --assume-yes \
  --dry-run \
  --keep-mounted >"$FLASH_LOG" 2>&1 || {
    cat "$FLASH_LOG" >&2 || true
    exit 1
  }
cat "$FLASH_LOG"

run_optional() {
  local label="$1"
  shift
  if ! command -v "$1" >/dev/null 2>&1; then
    warn "$label skipped because $1 is not installed"
    return 0
  fi
  log "Running $label"
  if ! "$@"; then
    warn "$label failed"
    return 1
  fi
  return 0
}

run_optional "pre-commit checks" pre-commit run --all-files --show-diff-on-failure
run_optional "spellcheck" pyspelling -c "$REPO_ROOT/.spellcheck.yaml"
run_optional "linkcheck" linkchecker --no-warnings "$REPO_ROOT/README.md" \
  "$REPO_ROOT/docs/"

log "Doctor checks complete"
