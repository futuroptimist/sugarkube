#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

err() {
  printf 'error: %s\n' "$*" >&2
}

die() {
  err "$1"
  exit "${2:-1}"
}

format_command() {
  local formatted=""
  local quoted part
  for part in "$@"; do
    printf -v quoted '%q' "$part"
    if [ -z "$formatted" ]; then
      formatted="$quoted"
    else
      formatted="$formatted $quoted"
    fi
  done
  printf '%s' "$formatted"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [ -n "${2:-}" ]; then
      die "$2"
    fi
    die "Missing required command: $1"
  fi
}

detect_os_arch() {
  local uname_s uname_m
  uname_s=$(uname -s)
  uname_m=$(uname -m)

  case "$uname_s" in
    Linux)
      BOOTSTRAP_OS="linux"
      ARCHIVE_EXT="tar.gz"
      ;;
    Darwin)
      BOOTSTRAP_OS="macOS"
      ARCHIVE_EXT="zip"
      ;;
    *)
      die "Unsupported operating system '$uname_s' for automatic gh installation"
      ;;
  esac

  case "$uname_m" in
    x86_64|amd64)
      BOOTSTRAP_ARCH="amd64"
      ;;
    arm64|aarch64)
      BOOTSTRAP_ARCH="arm64"
      ;;
    armv7l)
      BOOTSTRAP_ARCH="armv7"
      ;;
    armv6l)
      BOOTSTRAP_ARCH="armv6"
      ;;
    *)
      die "Unsupported architecture '$uname_m' for automatic gh installation"
      ;;
  esac
}

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print tolower($1)}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print tolower($1)}'
  else
    die "sha256sum or shasum is required to compute checksums"
  fi
}

expand_archive() {
  local archive="$1"
  local destination="$2"
  local tmp="$destination.tmp.$$"

  if command -v xz >/dev/null 2>&1; then
    if ! xz -T0 -dc "$archive" >"$tmp"; then
      rm -f "$tmp"
      die "Failed to expand $archive"
    fi
  else
    require_cmd python3 "python3 or xz is required to expand .xz archives"
    if ! python3 - "$archive" "$tmp" <<'PYCODE'; then
  import lzma
  import shutil
  import sys

  source, dest = sys.argv[1:3]
  with lzma.open(source, "rb") as src, open(dest, "wb") as dst:
      shutil.copyfileobj(src, dst)
PYCODE
      rm -f "$tmp"
      die "Failed to expand $archive"
    fi
  fi

  mv "$tmp" "$destination"
}

install_gh() {
  if [ -n "${SUGARKUBE_GH_INSTALL_HOOK:-}" ]; then
    log "Installing GitHub CLI via hook"
    if ! bash -c "$SUGARKUBE_GH_INSTALL_HOOK"; then
      die "Custom GitHub CLI installation hook failed"
    fi
    if command -v gh >/dev/null 2>&1; then
      return
    fi
    die "GitHub CLI not found after running hook"
  fi

  if command -v gh >/dev/null 2>&1; then
    return
  fi
  if [ "${SUGARKUBE_SKIP_GH_INSTALL:-0}" = "1" ]; then
    die "gh is required but installation was skipped via SUGARKUBE_SKIP_GH_INSTALL"
  fi

  detect_os_arch
  require_cmd curl "curl is required to install gh"
  if [ "$ARCHIVE_EXT" = "tar.gz" ]; then
    require_cmd tar "tar is required to install gh"
  else
    require_cmd unzip "unzip is required to install gh"
  fi

  local gh_version
  gh_version="${SUGARKUBE_GH_BOOTSTRAP_VERSION:-2.58.0}"
  if [ "$gh_version" = "latest" ]; then
    require_cmd python3 "python3 is required to determine the latest GitHub CLI version"
    local api_payload
    if ! api_payload=$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest); then
      die "Failed to determine latest GitHub CLI version"
    fi
    gh_version="$(printf '%s' "$api_payload" | python3 - <<'PYCODE'
import json
import sys

payload = json.load(sys.stdin)
tag = payload.get("tag_name") or ""
print(tag.lstrip("v"))
PYCODE
)"
    if [ -z "$gh_version" ]; then
      die "Failed to parse GitHub CLI version from release payload"
    fi
  fi

  local version_tag version_dir
  version_tag="v${gh_version#v}"
  version_dir="${gh_version#v}"

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir}"' RETURN

  local archive_url
  archive_url="https://github.com/cli/cli/releases/download/${version_tag}/gh_${version_dir}_${BOOTSTRAP_OS}_${BOOTSTRAP_ARCH}.${ARCHIVE_EXT}"
  local archive_path="$tmp_dir/gh.${ARCHIVE_EXT}"

  log "Downloading GitHub CLI ${version_dir} from $archive_url"
  if ! curl -fsSL "$archive_url" -o "$archive_path"; then
    die "Failed to download GitHub CLI archive"
  fi

  local extract_dir
  extract_dir="$tmp_dir/extracted"
  mkdir -p "$extract_dir"
  if [ "$ARCHIVE_EXT" = "tar.gz" ]; then
    if ! tar -xzf "$archive_path" -C "$extract_dir"; then
      die "Failed to extract GitHub CLI archive"
    fi
  else
    if ! unzip -q "$archive_path" -d "$extract_dir"; then
      die "Failed to extract GitHub CLI archive"
    fi
  fi

  local gh_dir
  gh_dir="$(find "$extract_dir" -maxdepth 1 -type d -name 'gh*' | head -n 1)"
  if [ -z "$gh_dir" ]; then
    die "Unable to locate gh binary in extracted archive"
  fi

  local install_dir
  install_dir="${SUGARKUBE_GH_INSTALL_DIR:-$HOME/.local/bin}"
  mkdir -p "$install_dir"
  if ! install "$gh_dir/bin/gh" "$install_dir/gh"; then
    die "Failed to install gh binary"
  fi
  chmod +x "$install_dir/gh"
  PATH="$install_dir:$PATH"
  export PATH
  log "Installed GitHub CLI ${version_dir} to $install_dir/gh"

  if ! command -v gh >/dev/null 2>&1; then
    die "GitHub CLI installation failed"
  fi

  rm -rf "$tmp_dir"
  trap - RETURN
}

usage() {
  cat <<'USAGE'
Install the latest sugarkube Pi image, verify checksums, and expand it to a raw
.img file. Intended to be used as a one-liner: curl -fsSL .../install_sugarkube_image.sh | bash

Usage: install_sugarkube_image.sh [options]

Options:
  -o, --output PATH       Destination for the compressed image (.img.xz). Defaults to
                          ~/sugarkube/images/sugarkube.img.xz
      --image PATH        Destination for the expanded .img file. Defaults to the
                          compressed path without the .xz suffix.
      --dir DIR           Directory to store downloads (shortcut to change the default
                          for both --output and --image).
      --release TAG       Download a specific release tag.
      --asset NAME        Override the release asset name (default: sugarkube.img.xz).
      --checksum NAME     Override the checksum asset name (default: asset + .sha256).
      --mode MODE         Pass through to download helper (auto, release, workflow).
      --download-only     Skip expansion; leave only the .img.xz and checksum.
      --dry-run           Preview the helper commands that would run without downloading
                          or expanding (prints "Dry run: would download …" etc.).
      --skip-gh-install   Do not attempt to bootstrap the GitHub CLI automatically.
      --download-script PATH
                          Use a local download_pi_image.sh instead of fetching from GitHub.
  -h, --help              Show this help message and exit.

Environment variables:
  SUGARKUBE_INSTALL_HELPER   Override the helper script path for tests/custom builds.
  SUGARKUBE_SKIP_GH_INSTALL  Skip automatic gh installation when set to 1.
  SUGARKUBE_GH_INSTALL_HOOK  Shell snippet used to install gh when it is missing.
  SUGARKUBE_GH_INSTALL_DIR   Directory to install gh into (default: ~/.local/bin).
  SUGARKUBE_IMAGE_DIR        Default image directory (default: ~/sugarkube/images).
  SUGARKUBE_IMAGE_ASSET      Default asset name (default: sugarkube.img.xz).
  SUGARKUBE_CHECKSUM_ASSET   Default checksum asset name.
  SUGARKUBE_RAW_BASE_URL     Base URL for fetching helper scripts (default: GitHub main).
USAGE
}

OWNER="${SUGARKUBE_OWNER:-futuroptimist}"
REPO="${SUGARKUBE_REPO:-sugarkube}"
DEFAULT_DIR="${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}"
ASSET_NAME="${SUGARKUBE_IMAGE_ASSET:-sugarkube.img.xz}"
CHECKSUM_NAME="${SUGARKUBE_CHECKSUM_ASSET:-${ASSET_NAME}.sha256}"

DOWNLOAD_ARGS=()
OUTPUT_ARCHIVE=""
IMAGE_DEST=""
DEST_DIR_OVERRIDE=""
DOWNLOAD_ONLY=0
DRY_RUN=0
SKIP_GH_INSTALL=0
HELPER_OVERRIDE="${SUGARKUBE_INSTALL_HELPER:-}"

print_dry_run_plan() {
  log "Dry run: would install GitHub CLI if missing (skipped)."

  if [ -n "$HELPER_OVERRIDE" ]; then
    log "Dry run: would use $HELPER_OVERRIDE to download $ASSET_NAME into $OUTPUT_ARCHIVE."
  else
    local raw_base
    raw_base="${SUGARKUBE_RAW_BASE_URL:-https://raw.githubusercontent.com/${OWNER}/${REPO}/main}"
    log "Dry run: would download helper from ${raw_base}/scripts/download_pi_image.sh."
    if [ "${#DOWNLOAD_ARGS[@]}" -gt 0 ]; then
      local formatted
      formatted="$(printf ' %q' "${DOWNLOAD_ARGS[@]}")"
      formatted="${formatted# }"
      log "Dry run: would run download helper with args: ${formatted}"
    else
      log "Dry run: would run download helper with default arguments."
    fi
  fi

  log "Dry run: would verify checksum $CHECKSUM_NAME."
  if [ "$DOWNLOAD_ONLY" -eq 1 ]; then
    log "Dry run: would skip expansion (--download-only)."
  else
    log "Dry run: would expand archive to $IMAGE_DEST."
  fi
  log "Dry run: would write checksum to ${IMAGE_DEST}.sha256."
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -o|--output)
      if [ "$#" -lt 2 ]; then
        die "--output requires a path"
      fi
      OUTPUT_ARCHIVE="$2"
      DOWNLOAD_ARGS+=("--output" "$2")
      shift 2
      ;;
    --image)
      if [ "$#" -lt 2 ]; then
        die "--image requires a path"
      fi
      IMAGE_DEST="$2"
      shift 2
      ;;
    --dir)
      if [ "$#" -lt 2 ]; then
        die "--dir requires a value"
      fi
      DEST_DIR_OVERRIDE="$2"
      DOWNLOAD_ARGS+=("--dir" "$2")
      shift 2
      ;;
    --release)
      if [ "$#" -lt 2 ]; then
        die "--release requires a tag"
      fi
      DOWNLOAD_ARGS+=("--release" "$2")
      shift 2
      ;;
    --asset)
      if [ "$#" -lt 2 ]; then
        die "--asset requires a value"
      fi
      ASSET_NAME="$2"
      DOWNLOAD_ARGS+=("--asset" "$2")
      shift 2
      ;;
    --checksum)
      if [ "$#" -lt 2 ]; then
        die "--checksum requires a value"
      fi
      CHECKSUM_NAME="$2"
      DOWNLOAD_ARGS+=("--checksum" "$2")
      shift 2
      ;;
    --mode)
      if [ "$#" -lt 2 ]; then
        die "--mode requires a value"
      fi
      MODE_OVERRIDE="$2"
      DOWNLOAD_ARGS+=("--mode" "$2")
      shift 2
      ;;
    --download-only)
      DOWNLOAD_ONLY=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-gh-install)
      SKIP_GH_INSTALL=1
      shift
      ;;
    --download-script)
      if [ "$#" -lt 2 ]; then
        die "--download-script requires a path"
      fi
      HELPER_OVERRIDE="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "Unknown option: $1"
      ;;
    *)
      die "Unexpected argument: $1"
      ;;
  esac
done

if [ "$SKIP_GH_INSTALL" -eq 1 ]; then
  SUGARKUBE_SKIP_GH_INSTALL=1
fi

if [ -n "$DEST_DIR_OVERRIDE" ]; then
  DEFAULT_DIR="$DEST_DIR_OVERRIDE"
fi

if [ -z "$OUTPUT_ARCHIVE" ]; then
  OUTPUT_ARCHIVE="${DEFAULT_DIR%/}/${ASSET_NAME}"
  DOWNLOAD_ARGS+=("--output" "$OUTPUT_ARCHIVE")
fi

if [ -z "$IMAGE_DEST" ]; then
  if [[ "$OUTPUT_ARCHIVE" == *.xz ]]; then
    IMAGE_DEST="${OUTPUT_ARCHIVE%.xz}"
  else
    IMAGE_DEST="${OUTPUT_ARCHIVE}.img"
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  print_dry_run_plan
  exit 0
fi

DEST_DIR="$(dirname "$OUTPUT_ARCHIVE")"
IMAGE_DIR="$(dirname "$IMAGE_DEST")"

if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry-run: would create directory $DEST_DIR"
  log "Dry-run: would create directory $IMAGE_DIR"
else
  mkdir -p "$DEST_DIR"
  mkdir -p "$IMAGE_DIR"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  if [ "$SKIP_GH_INSTALL" -eq 0 ]; then
    log "Dry-run: would install gh if it is missing"
  elif ! command -v gh >/dev/null 2>&1; then
    log "Dry-run: gh is not installed; rerun without --skip-gh-install after installing it"
  fi
else
  if [ "$SKIP_GH_INSTALL" -eq 0 ]; then
    install_gh
  else
    if ! command -v gh >/dev/null 2>&1; then
      die "gh is required; rerun without --skip-gh-install once it is installed"
    fi
  fi
  require_cmd curl "curl is required to download the helper"
fi

HELPER_SCRIPT=""
HELPER_TMP=""
HELPER_DISPLAY=""
cleanup_helper() {
  if [ -n "$HELPER_TMP" ] && [ -f "$HELPER_TMP" ]; then
    rm -f "$HELPER_TMP"
  fi
}
trap cleanup_helper EXIT

if [ -n "$HELPER_OVERRIDE" ]; then
  HELPER_DISPLAY="$HELPER_OVERRIDE"
  if [ ! -e "$HELPER_OVERRIDE" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "Dry-run: helper '$HELPER_OVERRIDE' does not exist; real execution would fail"
    else
      die "Download helper '$HELPER_OVERRIDE' does not exist"
    fi
  elif [ ! -x "$HELPER_OVERRIDE" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "Dry-run: helper '$HELPER_OVERRIDE' is not executable; real execution would fail"
    else
      die "Download helper '$HELPER_OVERRIDE' is not executable"
    fi
  fi
  HELPER_SCRIPT="$HELPER_OVERRIDE"
else
  RAW_BASE="${SUGARKUBE_RAW_BASE_URL:-https://raw.githubusercontent.com/${OWNER}/${REPO}/main}"
  HELPER_DISPLAY="$RAW_BASE/scripts/download_pi_image.sh"
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry-run: would download helper from $HELPER_DISPLAY"
    HELPER_SCRIPT="$HELPER_DISPLAY"
  else
    HELPER_TMP="$(mktemp)"
    if ! curl -fsSL "$RAW_BASE/scripts/download_pi_image.sh" -o "$HELPER_TMP"; then
      die "Failed to fetch download helper from $RAW_BASE"
    fi
    chmod +x "$HELPER_TMP"
    HELPER_SCRIPT="$HELPER_TMP"
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry-run: would download sugarkube image to $OUTPUT_ARCHIVE"
  if [ -n "$HELPER_SCRIPT" ]; then
    log "Dry-run: would invoke $(format_command "$HELPER_SCRIPT" "${DOWNLOAD_ARGS[@]}")"
  fi
else
  log "Downloading sugarkube image to $OUTPUT_ARCHIVE"
  if ! "$HELPER_SCRIPT" "${DOWNLOAD_ARGS[@]}"; then
    die "Download helper failed"
  fi
fi

if [ "$DOWNLOAD_ONLY" -eq 1 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry-run: would skip expansion (--download-only)."
    log "Dry-run: preview complete."
    exit 0
  fi
  log "Download complete. Skipping expansion (--download-only)."
  exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry-run: would expand $(basename "$OUTPUT_ARCHIVE") to $IMAGE_DEST"
  log "Dry-run: would write checksum to ${IMAGE_DEST}.sha256"
  log "Dry-run: preview complete."
  exit 0
fi

if [ ! -f "$OUTPUT_ARCHIVE" ]; then
  die "Expected archive $OUTPUT_ARCHIVE was not created"
fi

log "Expanding $(basename "$OUTPUT_ARCHIVE") to $IMAGE_DEST"
expand_archive "$OUTPUT_ARCHIVE" "$IMAGE_DEST"

local_sha="$(hash_file "$IMAGE_DEST")"
printf '%s  %s\n' "$local_sha" "$IMAGE_DEST" >"${IMAGE_DEST}.sha256"
log "Expanded image checksum: $local_sha"

log "Done. Image available at $IMAGE_DEST"
