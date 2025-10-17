#!/usr/bin/env bash
# Helper to inspect and update Raspberry Pi EEPROM boot order.
set -Eeuo pipefail

SCRIPT_NAME=$(basename "$0")

usage() {
  cat <<USAGE
Usage: ${SCRIPT_NAME} <command> [args]

Commands:
  ensure_order <hex>  Ensure BOOT_ORDER matches the provided hex value.
  print               Print current BOOT_ORDER and any PCIE_* keys.
USAGE
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "${SCRIPT_NAME}: Missing required command '$1'." >&2
    exit 1
  fi
}

run_rpi_eeprom_config() {
  if rpi-eeprom-config "$@"; then
    return 0
  fi
  if [[ ${EUID:-} -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    sudo rpi-eeprom-config "$@"
    return 0
  fi
  return 1
}

human_readable() {
  local order=$1
  case "${order,,}" in
    0xf416)
      echo "NVMe → SD → USB → repeat"
      ;;
    0xf461)
      echo "SD → NVMe → USB → repeat"
      ;;
    *)
      echo "Boot order ${order}"
      ;;
  esac
}

print_current() {
  require_command rpi-eeprom-config
  echo "[boot-order] Current EEPROM boot configuration:"
  run_rpi_eeprom_config | grep -E '^(BOOT_ORDER|PCIE_.*)=' || true
}

apply_boot_order() {
  local desired_raw=$1
  local desired=${desired_raw^^}

  if [[ ! ${desired} =~ ^0X[0-9A-F]+$ ]]; then
    echo "${SCRIPT_NAME}: BOOT_ORDER must be a hex value like 0xF461." >&2
    exit 1
  fi

  require_command mktemp
  require_command rpi-eeprom-config

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "${tmp_dir}"' EXIT

  local current_cfg="${tmp_dir}/current.conf"
  local target_cfg="${tmp_dir}/target.conf"

  if ! run_rpi_eeprom_config >"${current_cfg}"; then
    echo "${SCRIPT_NAME}: Failed to read current EEPROM configuration." >&2
    exit 1
  fi
  cp "${current_cfg}" "${target_cfg}"

  if grep -q '^BOOT_ORDER=' "${target_cfg}"; then
    sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=${desired}/" "${target_cfg}"
  else
    printf '\nBOOT_ORDER=%s\n' "${desired}" >>"${target_cfg}"
  fi

  if [[ -n "${PCIE_PROBE:-}" ]]; then
    if [[ "${PCIE_PROBE}" != "1" ]]; then
      echo "${SCRIPT_NAME}: PCIE_PROBE must be set to 1 when provided." >&2
      exit 1
    fi
    echo "[boot-order] Requesting PCIE_PROBE=${PCIE_PROBE}."
    if grep -q '^PCIE_PROBE=' "${target_cfg}"; then
      sed -i "s/^PCIE_PROBE=.*/PCIE_PROBE=${PCIE_PROBE}/" "${target_cfg}"
    else
      printf '\nPCIE_PROBE=%s\n' "${PCIE_PROBE}" >>"${target_cfg}"
    fi
  fi

  local human
  human=$(human_readable "${desired}")

  if cmp -s "${current_cfg}" "${target_cfg}"; then
    echo "[boot-order] BOOT_ORDER already ${desired} (${human})."
    print_current
    return
  fi

  echo "[boot-order] Applying BOOT_ORDER=${desired} (${human})."
  if [[ ${EUID:-} -ne 0 ]]; then
    sudo rpi-eeprom-config --apply "${target_cfg}"
  else
    rpi-eeprom-config --apply "${target_cfg}"
  fi

  print_current
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  local command=$1
  shift

  case "${command}" in
    ensure_order)
      if [[ $# -ne 1 ]]; then
        usage
        exit 1
      fi
      apply_boot_order "$1"
      ;;
    print)
      print_current
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "${SCRIPT_NAME}: Unknown command '${command}'." >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
