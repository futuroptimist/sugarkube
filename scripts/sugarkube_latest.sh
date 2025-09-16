#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DOWNLOAD_SCRIPT="$SCRIPT_DIR/download_pi_image.sh"

log() {
  printf 'sugarkube: %s\n' "$*"
}

if [[ ! -x "$DOWNLOAD_SCRIPT" ]]; then
  log "download script not found at $DOWNLOAD_SCRIPT"
  exit 1
fi

if ! command -v xz >/dev/null 2>&1; then
  log "xz is required"
  exit 1
fi

usage() {
  cat <<'EOF'
Usage: sugarkube_latest.sh [options] [-- <download-args>]

Download the most recent sugarkube image, verify it, and expand the archive.

Options:
  -d, --image-dir DIR    Directory to store artifacts (default: $HOME/sugarkube/images)
  -c, --compressed PATH  Override the compressed image path (passed to download script)
  -o, --output PATH      Expanded image output path (default: <compressed without .xz>)
      --no-expand        Skip expanding the image after download
  -h, --help             Show this help message

Additional arguments after `--` are forwarded to download_pi_image.sh.
EOF
}

DEFAULT_DIR=${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}
IMAGE_DIR="$DEFAULT_DIR"
COMPRESSED_OUTPUT=""
RAW_OUTPUT=""
EXPAND=1
FORWARDED=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--image-dir)
      IMAGE_DIR="$2"
      shift 2
      ;;
    -c|--compressed)
      COMPRESSED_OUTPUT="$2"
      shift 2
      ;;
    -o|--output)
      RAW_OUTPUT="$2"
      shift 2
      ;;
    --no-expand)
      EXPAND=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        FORWARDED+=("$1")
        shift
      done
      break
      ;;
    -r|--release|--repo|--asset|--checksum)
      FORWARDED+=("$1" "$2")
      shift 2
      ;;
    -f|--force|--skip-verify)
      FORWARDED+=("$1")
      shift
      ;;
    *)
      FORWARDED+=("$1")
      shift
      ;;
  esac
done

mkdir -p "$IMAGE_DIR"

if [[ -z "$COMPRESSED_OUTPUT" ]]; then
  COMPRESSED_OUTPUT="$IMAGE_DIR/sugarkube.img.xz"
fi

mkdir -p "$(dirname "$COMPRESSED_OUTPUT")"

if [[ -z "$RAW_OUTPUT" ]]; then
  if [[ "$COMPRESSED_OUTPUT" == *.xz ]]; then
    RAW_OUTPUT="${COMPRESSED_OUTPUT%.xz}"
  else
    RAW_OUTPUT="${COMPRESSED_OUTPUT}.img"
  fi
fi

# Avoid appending duplicate output flags if passed via --
append_output_flag=1
for arg in "${FORWARDED[@]}"; do
  if [[ "$arg" == "-o" || "$arg" == "--output" ]]; then
    append_output_flag=0
    break
  fi
done

if [[ $append_output_flag -eq 1 ]]; then
  FORWARDED+=("-o" "$COMPRESSED_OUTPUT")
fi

"$DOWNLOAD_SCRIPT" "${FORWARDED[@]}"

if [[ $EXPAND -eq 0 ]]; then
  log "Skipping image expansion (--no-expand specified)"
  exit 0
fi

mkdir -p "$(dirname "$RAW_OUTPUT")"

if [[ -f "$RAW_OUTPUT" && "$COMPRESSED_OUTPUT" -ot "$RAW_OUTPUT" ]]; then
  log "Expanded image already up to date at $RAW_OUTPUT"
  exit 0
fi

if [[ ! -f "$COMPRESSED_OUTPUT" ]]; then
  log "Compressed image not found at $COMPRESSED_OUTPUT"
  exit 1
fi

tmp_raw=$(mktemp)
trap "rm -f '$tmp_raw'" EXIT

log "Expanding $COMPRESSED_OUTPUT to $RAW_OUTPUT"
if ! xz -dc "$COMPRESSED_OUTPUT" > "$tmp_raw"; then
  rm -f "$tmp_raw"
  trap - EXIT
  log "Failed to expand image"
  exit 1
fi

mv "$tmp_raw" "$RAW_OUTPUT"
trap - EXIT
log "Expanded image saved to $RAW_OUTPUT"
