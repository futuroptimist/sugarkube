#!/usr/bin/env bash
# eeprom_nvme_first.sh - Ensure the Raspberry Pi bootloader prefers NVMe and enables PCIe probing.
# Usage: sudo scripts/eeprom_nvme_first.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/eeprom"
mkdir -p "${ARTIFACT_DIR}"
LOG_FILE="${ARTIFACT_DIR}/nvme-first.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

trap 'echo "[eeprom] failure" >&2' ERR

echo "[eeprom] Ensuring firmware utilities are available"
if ! command -v rpi-eeprom-update >/dev/null 2>&1; then
  echo "rpi-eeprom-update command not found. Install the rpi-eeprom package." >&2
  exit 1
fi

sudo_prefix=()
if [[ $(id -u) -ne 0 ]]; then
  sudo_prefix=(sudo)
fi

update_output="$(${sudo_prefix[@]} rpi-eeprom-update -a)"
printf '%s\n' "${update_output}"

orig_config="$(mktemp)"
trap 'rm -f "${orig_config}" "${orig_config}.new"' EXIT

${sudo_prefix[@]} rpi-eeprom-config --out "${orig_config}"
cp "${orig_config}" "${orig_config}.new"

set_config_value() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "${orig_config}.new"; then
    sed -i "s/^${key}=.*/${key}=${value}/" "${orig_config}.new"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${orig_config}.new"
  fi
}

set_config_value "BOOT_ORDER" "0xf416"
set_config_value "PCIE_PROBE" "1"

if cmp -s "${orig_config}" "${orig_config}.new"; then
  echo "[eeprom] Bootloader already prefers NVMe with PCIe probing enabled."
  exit 0
fi

${sudo_prefix[@]} rpi-eeprom-config --apply "${orig_config}.new"

echo "[eeprom] Updated bootloader configuration to prioritize NVMe (BOOT_ORDER=0xf416, PCIE_PROBE=1)."
