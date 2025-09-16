#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

err() {
  printf 'ERROR: %s\n' "$*" >&2
}

usage() {
  cat <<'USAGE'
Usage: install_sugarkube.sh [options]

Download the latest sugarkube Pi image, verify its checksum, and expand it
from .img.xz to a raw .img ready for flashing.

Options:
  -o, --output PATH       Write the raw image to PATH (default:
                          ~/sugarkube/images/sugarkube.img)
      --dir DIR           Directory for image output (default: ~/sugarkube/images)
      --release TAG       Download a specific GitHub release tag
      --download-script PATH_OR_URL
                          Use a custom download_pi_image.sh implementation
      --force             Overwrite existing files without prompting
      --dry-run           Show planned actions without downloading
      --yes               Automatically answer yes to installation prompts
      --help              Show this help message
USAGE
}

DEFAULT_OWNER="${SUGARKUBE_INSTALL_OWNER:-futuroptimist}"
DEFAULT_REPO="${SUGARKUBE_INSTALL_REPO:-sugarkube}"
DEFAULT_IMAGE_DIR="${SUGARKUBE_INSTALL_IMAGE_DIR:-$HOME/sugarkube/images}"
DEFAULT_IMAGE_NAME="${SUGARKUBE_INSTALL_IMAGE_NAME:-sugarkube.img}"
DEFAULT_DOWNLOAD_URL="${SUGARKUBE_INSTALL_DOWNLOAD_URL:-https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/download_pi_image.sh}"

OWNER="$DEFAULT_OWNER"
REPO="$DEFAULT_REPO"
OUTPUT_PATH=""
OUTPUT_DIR_OVERRIDE=""
RELEASE_TAG=""
DOWNLOAD_SOURCE=""
FORCE=0
DRY_RUN=0
ASSUME_YES=0

WORK_DIR=""

cleanup() {
  if [ -n "${WORK_DIR:-}" ] && [ -d "${WORK_DIR}" ]; then
    rm -rf "${WORK_DIR}"
  fi
}
trap cleanup EXIT

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -o|--output)
      if [ "$#" -lt 2 ]; then
        err "--output requires a path"
        exit 1
      fi
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --dir)
      if [ "$#" -lt 2 ]; then
        err "--dir requires a value"
        exit 1
      fi
      OUTPUT_DIR_OVERRIDE="$2"
      shift 2
      ;;
    --release)
      if [ "$#" -lt 2 ]; then
        err "--release requires a tag"
        exit 1
      fi
      RELEASE_TAG="$2"
      shift 2
      ;;
    --download-script)
      if [ "$#" -lt 2 ]; then
        err "--download-script requires a path or URL"
        exit 1
      fi
      DOWNLOAD_SOURCE="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    *)
      err "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

ASSUME_GH_INSTALL="${SUGARKUBE_INSTALLER_ASSUME_GH:-0}"

confirm() {
  if [ "$ASSUME_YES" -eq 1 ]; then
    return 0
  fi
  printf '%s [y/N]: ' "$1"
  read -r reply || return 1
  case "$reply" in
    y|Y|yes|YES)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "Missing required command: $1"
    exit 1
  fi
}

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print tolower($1)}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print tolower($1)}'
  else
    err "sha256sum or shasum is required"
    exit 1
  fi
}

maybe_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    printf '%s' ""
  elif command -v sudo >/dev/null 2>&1; then
    printf '%s' "sudo"
  else
    printf '%s' ""
  fi
}

install_gh() {
  if [ "$ASSUME_GH_INSTALL" = "1" ]; then
    log "gh missing but SUGARKUBE_INSTALLER_ASSUME_GH=1; skipping installation"
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    log "gh missing; dry-run mode skips installation"
    return 0
  fi
  local os
  os="$(uname -s)"
  log "gh not detected; attempting installation"
  if [ "$os" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
    if ! confirm "Install GitHub CLI (gh) via apt-get?"; then
      err "gh is required; aborting"
      exit 1
    fi
    local sudo_cmd
    sudo_cmd="$(maybe_sudo)"
    if [ -n "$sudo_cmd" ]; then
      $sudo_cmd apt-get update
      $sudo_cmd apt-get install -y gh
    else
      if [ "$(id -u)" -ne 0 ]; then
        err "Need sudo or root privileges to install gh"
        exit 1
      fi
      apt-get update
      apt-get install -y gh
    fi
  elif [ "$os" = "Linux" ] && command -v dnf >/dev/null 2>&1; then
    if ! confirm "Install GitHub CLI (gh) via dnf?"; then
      err "gh is required; aborting"
      exit 1
    fi
    local sudo_cmd
    sudo_cmd="$(maybe_sudo)"
    if [ -n "$sudo_cmd" ]; then
      $sudo_cmd dnf install -y gh
    else
      dnf install -y gh
    fi
  elif [ "$os" = "Linux" ] && command -v yum >/dev/null 2>&1; then
    if ! confirm "Install GitHub CLI (gh) via yum?"; then
      err "gh is required; aborting"
      exit 1
    fi
    local sudo_cmd
    sudo_cmd="$(maybe_sudo)"
    if [ -n "$sudo_cmd" ]; then
      $sudo_cmd yum install -y gh
    else
      yum install -y gh
    fi
  elif [ "$os" = "Linux" ] && command -v pacman >/dev/null 2>&1; then
    if ! confirm "Install GitHub CLI (gh) via pacman?"; then
      err "gh is required; aborting"
      exit 1
    fi
    local sudo_cmd
    sudo_cmd="$(maybe_sudo)"
    if [ -n "$sudo_cmd" ]; then
      $sudo_cmd pacman -Sy --noconfirm github-cli
    else
      pacman -Sy --noconfirm github-cli
    fi
  elif [ "$os" = "Darwin" ]; then
    if ! command -v brew >/dev/null 2>&1; then
      err "Homebrew is required to install gh on macOS"
      exit 1
    fi
    if ! confirm "Install GitHub CLI (gh) via brew?"; then
      err "gh is required; aborting"
      exit 1
    fi
    brew update
    brew install gh
  else
    err "Unsupported platform for automatic gh installation"
    exit 1
  fi
}

ensure_dependencies() {
  require_cmd curl
  require_cmd xz
  require_cmd dd
  if ! command -v gh >/dev/null 2>&1; then
    install_gh
  fi
  if ! command -v gh >/dev/null 2>&1; then
    err "gh is still missing after attempted installation"
    exit 1
  fi
}

resolve_output_path() {
  local base_dir
  if [ -n "$OUTPUT_DIR_OVERRIDE" ]; then
    base_dir="$OUTPUT_DIR_OVERRIDE"
  elif [ -n "$OUTPUT_PATH" ]; then
    base_dir="$(dirname "$OUTPUT_PATH")"
  else
    base_dir="$DEFAULT_IMAGE_DIR"
  fi
  mkdir -p "$base_dir"
  if [ -n "$OUTPUT_PATH" ]; then
    RAW_IMAGE_PATH="$OUTPUT_PATH"
  else
    RAW_IMAGE_PATH="${base_dir%/}/$DEFAULT_IMAGE_NAME"
  fi
  COMPRESSED_PATH="${RAW_IMAGE_PATH}.xz"
}

fetch_downloader() {
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ -n "$DOWNLOAD_SOURCE" ]; then
      if [ -f "$DOWNLOAD_SOURCE" ]; then
        DOWNLOADER="$DOWNLOAD_SOURCE"
      else
        DOWNLOADER="$DOWNLOAD_SOURCE"
      fi
    else
      DOWNLOADER="download_pi_image.sh"
    fi
    log "Dry run: skipping downloader fetch (${DOWNLOADER})"
    return
  fi
  if [ -n "$DOWNLOAD_SOURCE" ]; then
    if [ -f "$DOWNLOAD_SOURCE" ]; then
      DOWNLOADER="$DOWNLOAD_SOURCE"
      return
    fi
    DOWNLOADER_URL="$DOWNLOAD_SOURCE"
  else
    DOWNLOADER_URL="$DEFAULT_DOWNLOAD_URL"
  fi
  WORK_DIR="$(mktemp -d)"
  DOWNLOADER="${WORK_DIR}/download_pi_image.sh"
  log "Fetching downloader from ${DOWNLOADER_URL}"
  curl -fsSL "$DOWNLOADER_URL" -o "$DOWNLOADER"
  chmod +x "$DOWNLOADER"
}

run_download() {
  local args
  args=("$DOWNLOADER" "--output" "$COMPRESSED_PATH" "--dir" "$(dirname "$COMPRESSED_PATH")")
  if [ -n "$RELEASE_TAG" ]; then
    args+=("--release" "$RELEASE_TAG")
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run: would execute ${args[*]}"
    return
  fi
  SUGARKUBE_OWNER="$OWNER" \
    SUGARKUBE_REPO="$REPO" \
    "${args[@]}"
}

decompress_image() {
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run: would decompress $COMPRESSED_PATH to $RAW_IMAGE_PATH"
    return
  fi
  if [ ! -f "$COMPRESSED_PATH" ]; then
    err "Compressed image not found: $COMPRESSED_PATH"
    exit 1
  fi
  if [ -f "$RAW_IMAGE_PATH" ] && [ "$FORCE" -ne 1 ]; then
    err "Raw image already exists: $RAW_IMAGE_PATH (use --force to overwrite)"
    exit 1
  fi
  local tmp_img
  tmp_img="${RAW_IMAGE_PATH}.partial"
  log "Decompressing image (this may take a few minutes)"
  xz -dc "$COMPRESSED_PATH" >"$tmp_img"
  mv "$tmp_img" "$RAW_IMAGE_PATH"
  log "Expanded image written to $RAW_IMAGE_PATH"
}

print_summary() {
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run complete"
    return
  fi
  local checksum
  checksum=""
  if [ -f "${COMPRESSED_PATH}.sha256" ]; then
    checksum="$(awk '{print $1}' "${COMPRESSED_PATH}.sha256" | tr 'A-Z' 'a-z')"
  else
    checksum="$(sha256_file "$COMPRESSED_PATH")"
  fi
  log "SHA-256: $checksum"
  cat <<EON
Next steps:
  1. Flash the raw image with Raspberry Pi Imager or:
       xzcat "$COMPRESSED_PATH" | sudo dd of=/dev/sdX bs=8M status=progress
  2. Eject the media and boot the Pi. A first-boot report will appear under
     /boot/first-boot-report/ and /boot/first-boot-report.txt.
EON
}

ensure_dependencies
resolve_output_path
fetch_downloader
run_download
if [ "$DRY_RUN" -ne 1 ]; then
  if [ -f "$RAW_IMAGE_PATH" ] && [ "$FORCE" -ne 1 ]; then
    err "Raw image already exists: $RAW_IMAGE_PATH (use --force to overwrite)"
    exit 1
  fi
fi
decompress_image
print_summary
