#!/usr/bin/env bash
# eeprom_nvme_first.sh — ensure Pi 5 EEPROM prefers NVMe boot order with PCIE probing enabled.
# Usage: sudo just eeprom-nvme-first (safe to rerun; only applies when values differ).

set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo --preserve-env "$0" "$@"
fi

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_ROOT_DIR="${ARTIFACT_ROOT:-${REPO_ROOT}/artifacts}"
ARTIFACT_DIR="${ARTIFACT_ROOT_DIR}/eeprom"
LOG_FILE="${ARTIFACT_DIR}/eeprom.log"
mkdir -p "${ARTIFACT_DIR}"
touch "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

desired_boot="0xf416"
desired_probe="1"

if ! command -v rpi-eeprom-update >/dev/null 2>&1; then
  echo "rpi-eeprom-update not found; install rpi-eeprom package" >&2
  exit 1
fi

update_output=$(rpi-eeprom-update -a)
printf '%s\n' "${update_output}" >"${ARTIFACT_DIR}/update.txt"

current_config=$(rpi-eeprom-config)
printf '%s\n' "${current_config}" >"${ARTIFACT_DIR}/current.txt"
current_boot=$(printf '%s\n' "${current_config}" | awk -F'=' '/^BOOT_ORDER=/ {print $2}' | tail -n1)
current_probe=$(printf '%s\n' "${current_config}" | awk -F'=' '/^PCIE_PROBE=/ {print $2}' | tail -n1)

need_apply=0
[[ "${current_boot}" != "${desired_boot}" ]] && need_apply=1
[[ "${current_probe}" != "${desired_probe}" ]] && need_apply=1

if [[ "${need_apply}" -eq 0 ]]; then
  echo "EEPROM already configured (BOOT_ORDER=${current_boot:-unset}, PCIE_PROBE=${current_probe:-unset})"
  exit 0
fi

tmp_config=$(mktemp)
trap 'rm -f "${tmp_config}"' EXIT
printf '%s\n' "${current_config}" | grep -v '^BOOT_ORDER=' | grep -v '^PCIE_PROBE=' >"${tmp_config}"
cat <<CONFIG >>"${tmp_config}"
BOOT_ORDER=${desired_boot}
PCIE_PROBE=${desired_probe}
CONFIG

printf '%s\n' "Applying EEPROM config:" "$(cat "${tmp_config}")"
apply_output=$(rpi-eeprom-config --apply "${tmp_config}")
printf '%s\n' "${apply_output}" >"${ARTIFACT_DIR}/apply.txt"

echo "EEPROM updated → BOOT_ORDER=${desired_boot}, PCIE_PROBE=${desired_probe}"
