#!/usr/bin/env bash
# Purpose: Ensure the rpi-clone utility is installed and up to date.
# Usage: sudo ./scripts/install_rpi_clone.sh
set -Eeuo pipefail

INSTALL_URL="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"

if command -v rpi-clone >/dev/null 2>&1; then
  location=$(command -v rpi-clone)
  echo "[install-rpi-clone] rpi-clone already installed at ${location}" \
    "(skip installation)."
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to install rpi-clone" >&2
  exit 1
fi

if [[ ${EUID:-0} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo "$0" "$@"
  fi
  echo "This script requires root privileges." >&2
  exit 1
fi

echo "[install-rpi-clone] Installing rpi-clone from ${INSTALL_URL}" >&2
if curl -fsSL "${INSTALL_URL}" | bash; then
  echo "[install-rpi-clone] Installation complete"
else
  echo "[install-rpi-clone] Installation failed" >&2
  exit 1
fi
