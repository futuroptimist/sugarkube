#!/usr/bin/env bash
set -euo pipefail

LOG_PREFIX="[sugarkube-install]"

log() {
  printf '%s %s\n' "$LOG_PREFIX" "$*"
}

err() {
  printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2
}

die() {
  err "$1"
  exit "${2:-1}"
}

usage() {
  cat <<'USAGE'
Install the latest sugarkube Pi image with checksum verification.

Usage: install_sugarkube.sh [options]

Options:
  --dir DIR        Destination directory for artifacts (default: $HOME/sugarkube/images)
  --release TAG    Download a specific release tag instead of the latest
  --asset NAME     Override the image asset name (default: sugarkube.img.xz)
  --checksum NAME  Override checksum asset name (default: asset + .sha256)
  --image NAME     Name for the expanded image (default: asset without .xz)
  --keep-xz        Preserve the compressed artifact after expansion
  --force          Overwrite existing files in the destination directory
  --skip-deps      Skip dependency installation (mainly for CI/testing)
  -h, --help       Show this help message

Environment:
  SUGARKUBE_OWNER, SUGARKUBE_REPO override the GitHub project (defaults
  futuroptimist/sugarkube).
  SUGARKUBE_IMAGE_DIR overrides the default destination directory.
  SUGARKUBE_INSTALL_SKIP_DEPS=1 bypasses dependency installation.
USAGE
}

OWNER="${SUGARKUBE_OWNER:-futuroptimist}"
REPO="${SUGARKUBE_REPO:-sugarkube}"
ASSET="${SUGARKUBE_IMAGE_ASSET:-sugarkube.img.xz}"
CHECKSUM="${SUGARKUBE_CHECKSUM_ASSET:-${ASSET}.sha256}"
DEST_DIR="${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}"
RELEASE_TAG=""
IMAGE_NAME=""
KEEP_XZ=0
FORCE=0
SKIP_DEPS=${SUGARKUBE_INSTALL_SKIP_DEPS:-0}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      [ "$#" -ge 2 ] || die "--dir requires an argument"
      DEST_DIR="$2"
      shift 2
      ;;
    --release)
      [ "$#" -ge 2 ] || die "--release requires an argument"
      RELEASE_TAG="$2"
      shift 2
      ;;
    --asset)
      [ "$#" -ge 2 ] || die "--asset requires an argument"
      ASSET="$2"
      shift 2
      ;;
    --checksum)
      [ "$#" -ge 2 ] || die "--checksum requires an argument"
      CHECKSUM="$2"
      shift 2
      ;;
    --image)
      [ "$#" -ge 2 ] || die "--image requires an argument"
      IMAGE_NAME="$2"
      shift 2
      ;;
    --keep-xz)
      KEEP_XZ=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --skip-deps)
      SKIP_DEPS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

if [ -z "$IMAGE_NAME" ]; then
  IMAGE_NAME="${ASSET%.xz}"
  if [ "$IMAGE_NAME" = "$ASSET" ]; then
    IMAGE_NAME="${ASSET}.img"
  fi
fi

mkdir -p "$DEST_DIR"
[ -d "$DEST_DIR" ] || die "Failed to create destination directory '$DEST_DIR'"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [ -n "${2:-}" ]; then
      die "$2"
    else
      die "Missing required command: $1"
    fi
  fi
}

available_sha256_tool() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "sha256sum"
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "shasum"
  else
    return 1
  fi
}

install_gh_linux() {
  local installer
  installer=$(command -v apt-get 2>/dev/null || true)
  if [ -z "$installer" ]; then
    return 1
  fi
  if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo apt-get update -qq && sudo apt-get install -y gh >/dev/null 2>&1
    else
      return 1
    fi
  else
    apt-get update -qq && apt-get install -y gh >/dev/null 2>&1
  fi
}

install_gh_macos() {
  if ! command -v brew >/dev/null 2>&1; then
    return 1
  fi
  brew install gh >/dev/null 2>&1
}

ensure_gh() {
  if command -v gh >/dev/null 2>&1; then
    return 0
  fi
  if [ "$SKIP_DEPS" = "1" ]; then
    err "gh missing and dependency installation skipped"
    return 1
  fi
  log "Installing GitHub CLI (gh)"
  local os
  os="$(uname -s 2>/dev/null || echo unknown)"
  case "$os" in
    Linux)
      install_gh_linux || die "Failed to install gh; install it manually and re-run"
      ;;
    Darwin)
      install_gh_macos || die "Failed to install gh via Homebrew"
      ;;
    *)
      die "Unsupported OS '$os' for automatic gh installation"
      ;;
  esac
  if ! command -v gh >/dev/null 2>&1; then
    die "gh installation did not succeed"
  fi
}

ensure_deps() {
  require_cmd curl "curl is required"
  if ! available_sha256_tool >/dev/null 2>&1; then
    die "Install sha256sum (coreutils) or shasum before running"
  fi
  if ! command -v xz >/dev/null 2>&1 && ! command -v unxz >/dev/null 2>&1; then
    die "Install xz-utils to decompress the image"
  fi
}

decompress_file() {
  local src="$1"
  if command -v xz >/dev/null 2>&1; then
    xz --decompress --stdout "$src"
  else
    unxz -c "$src"
  fi
}

decompress_stream() {
  if command -v xz >/dev/null 2>&1; then
    xz --decompress --stdout -
  else
    unxz -c -
  fi
}

sha256_check() {
  local checksum_file="$1"
  local work_dir="$2"
  local tool
  tool="$(available_sha256_tool)"
  case "$tool" in
    sha256sum)
      (cd "$work_dir" && sha256sum --check "$(basename "$checksum_file")" >/dev/null)
      ;;
    shasum)
      (cd "$work_dir" && shasum -a 256 -c "$(basename "$checksum_file")" >/dev/null)
      ;;
    *)
      die "No SHA-256 tool available"
      ;;
  esac
}

cleanup() {
  if [ -n "${TMP_DIR:-}" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}

ensure_deps
ensure_gh

TMP_DIR="$(mktemp -d)"
trap cleanup EXIT

DOWNLOAD_DIR="$TMP_DIR/download"
mkdir -p "$DOWNLOAD_DIR"

log "Downloading ${ASSET}"
GH_ARGS=(
  release
  download
  --repo "$OWNER/$REPO"
  --dir "$DOWNLOAD_DIR"
  --clobber
  --pattern "$ASSET"
  --pattern "$CHECKSUM"
)
if [ -n "$RELEASE_TAG" ]; then
  GH_ARGS+=(--tag "$RELEASE_TAG")
fi

if ! gh "${GH_ARGS[@]}" >/dev/null; then
  die "gh failed to download release assets"
fi

IMAGE_XZ="$DOWNLOAD_DIR/$ASSET"
CHECKSUM_FILE="$DOWNLOAD_DIR/$CHECKSUM"
[ -f "$IMAGE_XZ" ] || die "Downloaded artifact missing: $IMAGE_XZ"
[ -f "$CHECKSUM_FILE" ] || die "Checksum file missing: $CHECKSUM_FILE"

log "Verifying checksum"
sha256_check "$CHECKSUM_FILE" "$DOWNLOAD_DIR" || die "Checksum verification failed"

DEST_IMAGE="$DEST_DIR/$IMAGE_NAME"
DEST_XZ="$DEST_DIR/$ASSET"
if [ "$FORCE" -ne 1 ]; then
  if [ -f "$DEST_IMAGE" ]; then
    die "Destination image $DEST_IMAGE already exists (use --force to overwrite)"
  fi
  if [ -f "$DEST_XZ" ] && [ "$KEEP_XZ" -eq 1 ]; then
    die "Compressed artifact $DEST_XZ already exists (use --force to overwrite)"
  fi
fi

if [ "$KEEP_XZ" -eq 1 ]; then
  cp "$IMAGE_XZ" "$DEST_XZ"
  cp "$CHECKSUM_FILE" "$DEST_XZ.sha256"
fi

log "Expanding image to $DEST_IMAGE"
if command -v pv >/dev/null 2>&1; then
  if [[ "$IMAGE_XZ" == *.xz ]]; then
    pv "$IMAGE_XZ" | decompress_stream >"$DEST_IMAGE"
  else
    pv "$IMAGE_XZ" >"$DEST_IMAGE"
  fi
else
  if [[ "$IMAGE_XZ" == *.xz ]]; then
    decompress_file "$IMAGE_XZ" >"$DEST_IMAGE"
  else
    cp "$IMAGE_XZ" "$DEST_IMAGE"
  fi
fi

sync

log "Image ready: $DEST_IMAGE"
if [ "$KEEP_XZ" -eq 1 ]; then
  log "Compressed artifact preserved at $DEST_XZ"
fi
