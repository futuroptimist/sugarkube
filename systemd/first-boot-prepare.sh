#!/usr/bin/env bash
# first-boot-prepare.sh - One-time provisioning for NVMe migration readiness.
# Usage: systemd unit first-boot-prepare.service executes this on first boot.
# Installs firmware tools, rpi-clone, optionally enforces NVMe boot order, and logs progress.

set -Eeuo pipefail

LOG_FILE="/var/log/first-boot-prepare.log"
STATE_DIR="/var/lib/sugarkube"
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
SCRIPT_ROOT="/opt/sugarkube"
NVME_SCRIPT="${SCRIPT_ROOT}/scripts/eeprom_nvme_first.sh"
CLONE_INSTALL_URL="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"

mkdir -p "${STATE_DIR}"
exec >>"${LOG_FILE}" 2>&1
printf '[first-boot-prepare] %s starting\n' "$(date --iso-8601=seconds)"

if [ -f "${STATE_FILE}" ]; then
  printf '[first-boot-prepare] already completed; exiting\n'
  exit 0
fi

ensure_package() {
  local pkg="$1"
  if dpkg -s "${pkg}" >/dev/null 2>&1; then
    return
  fi
  printf '[first-boot-prepare] installing %s\n' "${pkg}"
  if ! DEBIAN_FRONTEND=noninteractive apt-get update -y; then
    printf '[first-boot-prepare] apt-get update failed for %s\n' "${pkg}"
    return 1
  fi
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y "${pkg}"; then
    printf '[first-boot-prepare] apt-get install failed for %s\n' "${pkg}"
    return 1
  fi
}

install_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    printf '[first-boot-prepare] rpi-clone already installed\n'
    return
  fi
  printf '[first-boot-prepare] installing rpi-clone from maintained fork\n'
  curl -fsSL "${CLONE_INSTALL_URL}" | bash
}

main() {
  ensure_package rpi-eeprom
  ensure_package ethtool
  ensure_package jq
  if ! ensure_package network-manager; then
    printf '[first-boot-prepare] network-manager optional; continuing\n'
  fi

  install_rpi_clone

  if [ -x "${NVME_SCRIPT}" ] && [ "${SKIP_EEPROM:-0}" != "1" ]; then
    printf '[first-boot-prepare] ensuring EEPROM prefers NVMe boot\n'
    sudo "${NVME_SCRIPT}"
  else
    printf '[first-boot-prepare] skipping EEPROM configuration (script missing or SKIP_EEPROM=1)\n'
  fi

  touch "${STATE_FILE}"
  printf '[first-boot-prepare] completed successfully\n'
}

main "$@"
