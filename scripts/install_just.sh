#!/usr/bin/env bash
set -euo pipefail

# Install the `just` command in a portable location so development and CI runs can rely on it
# without manual setup. The script prefers a local tarball when provided via
# SUGARKUBE_JUST_TARBALL to keep tests hermetic and falls back to the official release
# archives otherwise.

INSTALL_DIR="${SUGARKUBE_JUST_BIN_DIR:-${HOME}/.local/bin}"
TARGET="${SUGARKUBE_JUST_TARGET:-}"
TARBALL="${SUGARKUBE_JUST_TARBALL:-}"

log() {
  echo "[sugarkube] $*" >&2
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
    if sudo -n apt-get update >/dev/null 2>&1 && \
       sudo -n apt-get install -y just >/dev/null 2>&1; then
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
  DOWNLOAD_URL="${SUGARKUBE_JUST_URL:-${base_url}/just-${TARGET}.tar.gz}"
  if command -v curl >/dev/null 2>&1; then
    downloader=(curl -fsSL "$DOWNLOAD_URL")
  elif command -v wget >/dev/null 2>&1; then
    downloader=(wget -qO- "$DOWNLOAD_URL")
  else
    log "Neither curl nor wget is available to download just"
    exit 1
  fi

  TARBALL="$(mktemp -t just-XXXXXXXX.tar.gz)"
  cleanup_tarball="$TARBALL"
  if ! "${downloader[@]}" >"$TARBALL"; then
    log "Failed to download just from $DOWNLOAD_URL"
    rm -f "$TARBALL"
    exit 1
  fi
fi

if [ ! -f "$TARBALL" ]; then
  log "Tarball $TARBALL does not exist"
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
