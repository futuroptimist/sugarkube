#!/usr/bin/env bash
# first-boot-prepare.sh - Prime Pi firmware tools and NVMe helpers during the first boot.
# Usage: systemd service (first-boot-prepare.service)
set -euo pipefail

LOG_FILE="/var/log/first-boot-prepare.log"
STATE_DIR="/var/lib/sugarkube"
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
export DEBIAN_FRONTEND=noninteractive
mkdir -p "${STATE_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "[first-boot] Starting first boot preparation at $(date --iso-8601=seconds)"
if [[ -f "${STATE_FILE}" ]]; then
  echo "[first-boot] Preparation already completed; exiting."
  exit 0
fi

APT_UPDATED=0
apt_update_once() {
  if [[ ${APT_UPDATED} -eq 0 ]]; then
    if apt-get update; then
      APT_UPDATED=1
    else
      echo "[first-boot] apt-get update failed" >&2
    fi
  fi
}

ensure_package() {
  local package="$1"
  if dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -q "install ok installed"; then
    return
  fi
  echo "[first-boot] Installing ${package}"
  apt_update_once
  if ! apt-get install -y "${package}"; then
    echo "[first-boot] Failed to install ${package}" >&2
  fi
}

ensure_package rpi-eeprom

sudo_prefix=()
if [[ $(id -u) -ne 0 ]]; then
  sudo_prefix=(sudo)
fi

if ! command -v rpi-clone >/dev/null 2>&1; then
  echo "[first-boot] Installing rpi-clone"
  if ! curl -fsSL https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install | "${sudo_prefix[@]}" bash; then
    echo "[first-boot] Failed to install rpi-clone" >&2
  fi
else
  echo "[first-boot] rpi-clone already present"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${REPO_ROOT}/scripts/eeprom_nvme_first.sh" ]]; then
  echo "[first-boot] Applying NVMe-first EEPROM configuration"
  if ! "${REPO_ROOT}/scripts/eeprom_nvme_first.sh"; then
    echo "[first-boot] EEPROM configuration helper failed" >&2
  fi
else
  echo "[first-boot] eeprom_nvme_first.sh not found; skipping"
fi

sync
printf '%s\n' "completed $(date --iso-8601=seconds)" >"${STATE_FILE}"
chmod 600 "${STATE_FILE}"
echo "[first-boot] Preparation complete"
