#!/usr/bin/env bash
# eeprom_nvme_first.sh - Ensure Raspberry Pi EEPROM favors NVMe boot.
# Usage: sudo ./scripts/eeprom_nvme_first.sh
# Applies firmware updates, sets BOOT_ORDER=0xf416 and PCIE_PROBE=1 when not already configured.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/artifacts/eeprom"
LOG_FILE="${ARTIFACT_DIR}/eeprom.log"
mkdir -p "${ARTIFACT_DIR}"
: >"${LOG_FILE}"

log() {
  printf '%s\n' "$1" | tee -a "${LOG_FILE}"
}

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    log "Required command '${cmd}' missing"
    exit 1
  fi
}

apply_config() {
  local cfg_file="$1"
  sudo rpi-eeprom-config --apply "${cfg_file}" | tee -a "${LOG_FILE}"
}

main() {
  require_command rpi-eeprom-update
  require_command rpi-eeprom-config

  log "[eeprom] Updating bootloader to latest stable"
  sudo rpi-eeprom-update -a | tee -a "${LOG_FILE}"

  local current_cfg desired_boot desired_probe needs_update=0
  current_cfg=$(sudo rpi-eeprom-config)
  desired_boot="0xf416"
  desired_probe="1"

  local current_boot current_probe
  current_boot=$(printf '%s\n' "${current_cfg}" | awk -F'=' '/^BOOT_ORDER=/{print tolower($2)}')
  current_probe=$(printf '%s\n' "${current_cfg}" | awk -F'=' '/^PCIE_PROBE=/{print tolower($2)}')

  if [ "${current_boot}" != "${desired_boot}" ]; then
    needs_update=1
  fi
  if [ "${current_probe}" != "${desired_probe}" ]; then
    needs_update=1
  fi

  if [ "${needs_update}" -eq 0 ]; then
    log "[eeprom] BOOT_ORDER and PCIE_PROBE already set; nothing to do"
    exit 0
  fi

  local tmp_file
  tmp_file="$(mktemp)"
  trap 'rm -f "${tmp_file}"' EXIT

  printf 'BOOT_ORDER=%s\nPCIE_PROBE=%s\n' "${desired_boot}" "${desired_probe}" >"${tmp_file}"
  log "[eeprom] Applying NVMe-first boot configuration"
  apply_config "${tmp_file}"
  log "[eeprom] Configuration applied"
}

main "$@"
