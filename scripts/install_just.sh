#!/usr/bin/env bash
set -euo pipefail

# Install the `just` command in a portable location so development and CI runs can rely on it
# without manual setup. The script prefers a local tarball when provided via
# SUGARKUBE_JUST_TARBALL to keep tests hermetic and falls back to the official release
# archives otherwise.

INSTALL_DIR="${SUGARKUBE_JUST_BIN_DIR:-${HOME}/.local/bin}"
TARGET="${SUGARKUBE_JUST_TARGET:-}"
TARBALL="${SUGARKUBE_JUST_TARBALL:-}"
JUST_URL="${SUGARKUBE_JUST_URL:-}"
EXPECTED_SHA256="${SUGARKUBE_JUST_SHA256:-}"
SHA256_URL="${SUGARKUBE_JUST_SHA256_URL:-}"

log() {
  echo "[sugarkube] $*" >&2
}

hash_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print tolower($1)}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print tolower($1)}'
    return 0
  fi
  log "sha256sum or shasum is required to verify just downloads"
  return 1
}

download_to_file() {
  local url="$1"
  local output="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" >"$output"
    return $?
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -qO- "$url" >"$output"
    return $?
  fi

  log "Neither curl nor wget is available to download $url"
  return 1
}

verify_tarball_checksum() {
  local tarball="$1"
  local expected="${EXPECTED_SHA256,,}"

  if [ -z "$expected" ]; then
    if [ -n "$SHA256_URL" ]; then
      local checksum_file
      checksum_file="$(mktemp -t just-sha256-XXXXXXXX.txt)"
      if ! download_to_file "$SHA256_URL" "$checksum_file"; then
        rm -f "$checksum_file"
        log "Failed to download checksum from $SHA256_URL"
        return 1
      fi
      expected="$(awk 'NF {print tolower($1); exit}' "$checksum_file")"
      rm -f "$checksum_file"
    fi
  fi

  if [ -z "$expected" ]; then
    log "Missing checksum: set SUGARKUBE_JUST_SHA256 or SUGARKUBE_JUST_SHA256_URL"
    return 1
  fi

  if ! printf '%s' "$expected" | grep -Eq '^[a-f0-9]{64}$'; then
    log "Checksum '$expected' is not a valid SHA-256 digest"
    return 1
  fi

  local actual
  actual="$(hash_file "$tarball")" || return 1
  if [ "$actual" != "$expected" ]; then
    log "Checksum mismatch for $tarball"
    return 1
  fi

  return 0
}

if [ -z "${SUGARKUBE_JUST_FORCE_INSTALL:-}" ] && command -v just >/dev/null 2>&1; then
  log "just already installed"
  exit 0
fi

try_apt_install() {
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi

  if [ "$(id -u)" -eq 0 ]; then
    if apt-get update >/dev/null 2>&1 && apt-get install -y just >/dev/null 2>&1; then
      if ! command -v just >/dev/null 2>&1; then
        log "apt-get reported success but just is not on PATH"
        return 1
      fi
      return 0
    fi
    return 1
  fi

  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    if sudo -n apt-get update >/dev/null 2>&1 &&        sudo -n apt-get install -y just >/dev/null 2>&1; then
      return 0
    fi
  fi

  return 1
}

if [ -z "$TARGET" ]; then
  case "$(uname -s)" in
    Linux)
      arch=$(uname -m)
      case "$arch" in
        x86_64|amd64)
          TARGET="x86_64-unknown-linux-musl"
          ;;
        aarch64|arm64)
          TARGET="aarch64-unknown-linux-musl"
          ;;
        *)
          log "Unsupported architecture '$arch' for automatic just installation"
          exit 1
          ;;
      esac
      ;;
    Darwin)
      arch=$(uname -m)
      case "$arch" in
        x86_64|amd64)
          TARGET="x86_64-apple-darwin"
          ;;
        aarch64|arm64)
          TARGET="aarch64-apple-darwin"
          ;;
        *)
          log "Unsupported architecture '$arch' for automatic just installation"
          exit 1
          ;;
      esac
      ;;
    *)
      log "Unsupported platform '$(uname -s)' for automatic just installation"
      exit 1
      ;;
  esac
fi

mkdir -p "$INSTALL_DIR"

cleanup_tarball=""
if [ -z "$TARBALL" ]; then
  if try_apt_install; then
    log "Installed just via apt-get"
    exit 0
  fi

  base_url="https://github.com/casey/just/releases/latest/download"
  DOWNLOAD_URL="${JUST_URL:-${base_url}/just-${TARGET}.tar.gz}"

  if [ -z "$SHA256_URL" ]; then
    if [ -n "$JUST_URL" ] && [ -z "$EXPECTED_SHA256" ]; then
      log "SUGARKUBE_JUST_URL requires SUGARKUBE_JUST_SHA256 or SUGARKUBE_JUST_SHA256_URL"
      exit 1
    fi
    SHA256_URL="${DOWNLOAD_URL}.sha256"
  fi

  TARBALL="$(mktemp -t just-XXXXXXXX.tar.gz)"
  cleanup_tarball="$TARBALL"
  if ! download_to_file "$DOWNLOAD_URL" "$TARBALL"; then
    log "Failed to download just from $DOWNLOAD_URL"
    rm -f "$TARBALL"
    exit 1
  fi
fi

if [ ! -f "$TARBALL" ]; then
  log "Tarball $TARBALL does not exist"
  exit 1
fi

if ! verify_tarball_checksum "$TARBALL"; then
  rm -f "$cleanup_tarball"
  exit 1
fi

tar -xzf "$TARBALL" -C "$INSTALL_DIR" just
chmod +x "$INSTALL_DIR/just"

if [ ! -x "$INSTALL_DIR/just" ]; then
  log "just binary not found in $INSTALL_DIR after extraction"
  exit 1
fi

if [ -n "$cleanup_tarball" ]; then
  rm -f "$cleanup_tarball"
fi

log "Installed just to $INSTALL_DIR"
exit 0
