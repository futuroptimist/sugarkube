#!/usr/bin/env bash
# Purpose: Ensure Raspberry Pi EEPROM prefers NVMe boot with up-to-date firmware.
# Usage: sudo ./scripts/eeprom_nvme_first.sh
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
mkdir -p "${ARTIFACT_DIR}"
LOG_FILE="${ARTIFACT_DIR}/eeprom-nvme-first.log"
exec > >(tee "${LOG_FILE}") 2>&1

if [[ ${EUID} -ne 0 ]]; then
  echo "This script must run with sudo/root privileges." >&2
  exit 1
fi

if ! command -v rpi-eeprom-update >/dev/null 2>&1; then
  echo "rpi-eeprom-update not found; install the rpi-eeprom package first." >&2
  exit 1
fi

if ! command -v rpi-eeprom-config >/dev/null 2>&1; then
  echo "rpi-eeprom-config not found; install the rpi-eeprom package first." >&2
  exit 1
fi

echo "[eeprom] Checking for firmware updates (rpi-eeprom-update -a)"
UPDATE_OUTPUT=$(rpi-eeprom-update -a 2>&1 || true)
echo "${UPDATE_OUTPUT}"

TMP_DIR=$(mktemp -d)
CURRENT_CFG="${TMP_DIR}/current.conf"
TARGET_CFG="${TMP_DIR}/target.conf"
trap 'rm -rf "${TMP_DIR}"' EXIT

if ! rpi-eeprom-config >"${CURRENT_CFG}"; then
  echo "Failed to read current EEPROM configuration" >&2
  exit 1
fi
cp "${CURRENT_CFG}" "${TARGET_CFG}"

if grep -q '^BOOT_ORDER=' "${TARGET_CFG}"; then
  sed -i 's/^BOOT_ORDER=.*/BOOT_ORDER=0xf416/' "${TARGET_CFG}"
else
  printf '\nBOOT_ORDER=0xf416\n' >>"${TARGET_CFG}"
fi

if grep -q '^PCIE_PROBE=' "${TARGET_CFG}"; then
  sed -i 's/^PCIE_PROBE=.*/PCIE_PROBE=1/' "${TARGET_CFG}"
else
  printf '\nPCIE_PROBE=1\n' >>"${TARGET_CFG}"
fi

if cmp -s "${CURRENT_CFG}" "${TARGET_CFG}"; then
  echo "[eeprom] BOOT_ORDER and PCIE_PROBE already set; no changes applied."
  exit 0
fi

echo "[eeprom] Applying updated EEPROM configuration"
if ! rpi-eeprom-config --apply "${TARGET_CFG}"; then
  echo "Failed to apply EEPROM configuration" >&2
  exit 1
fi

echo "[eeprom] EEPROM configuration updated to prefer NVMe boot (BOOT_ORDER=0xf416, PCIE_PROBE=1)."
