#!/usr/bin/env bash
# Helper for Raspberry Pi boot order management.
# Usage:
#   ./scripts/boot_order.sh ensure_order 0xf461
#   ./scripts/boot_order.sh print
set -Eeuo pipefail

command_name=${1:-}

usage() {
  cat <<'USAGE'
Usage:
  boot_order.sh ensure_order <hex>
  boot_order.sh print

Environment:
  PCIE_PROBE=1   Append or update PCIE_PROBE=1 when ensuring boot order.
USAGE
}

if [[ -z "${command_name}" ]]; then
  usage
  exit 1
fi

ensure_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[boot-order] Missing required command: $1" >&2
    exit 1
  fi
}

ensure_command rpi-eeprom-config

maybe_sudo() {
  if [[ ${EUID} -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

read_config() {
  maybe_sudo rpi-eeprom-config
}

write_config() {
  local template_file=$1
  local editor_cmd='bash -c '\''cat "$BOOT_ORDER_TEMPLATE" > "$1"'\''
  if [[ ${EUID} -eq 0 ]]; then
    BOOT_ORDER_TEMPLATE="${template_file}" EDITOR="${editor_cmd}" rpi-eeprom-config --edit >/dev/null
  else
    sudo env BOOT_ORDER_TEMPLATE="${template_file}" EDITOR="${editor_cmd}" rpi-eeprom-config --edit >/dev/null
  fi
}

hex=${2:-}

sanitize_hex() {
  local value=$1
  if [[ ! ${value} =~ ^0x[0-9a-fA-F]+$ ]]; then
    echo "[boot-order] Invalid hex value: ${value}" >&2
    exit 1
  fi
  printf '%s' "${value,,}"
}

interpret_digit() {
  case "$1" in
    0) printf 'Restart from top' ;;
    1) printf 'SD card' ;;
    2) printf 'Network boot' ;;
    3) printf 'USB 2 (type A)' ;;
    4) printf 'USB mass storage' ;;
    5) printf 'USB 2 boot' ;;
    6) printf 'NVMe' ;;
    7) printf 'SD card (rescan)' ;;
    8) printf 'USB (rescan)' ;;
    9) printf 'USB boot (fallback)' ;;
    a) printf 'Network boot (repeat)' ;;
    b) printf 'Boot from BCM-USB MSD' ;;
    c) printf 'NVMe (rescan)' ;;
    d) printf 'HTTP boot' ;;
    e) printf 'Recover EEPROM' ;;
    f) printf 'Repeat from first entry' ;;
    *) printf 'Unknown (%s)' "$1" ;;
  esac
}

print_interpretation() {
  local value=$(sanitize_hex "$1")
  local digits=${value#0x}
  local len=${#digits}
  local outputs=()
  for (( idx=len-1; idx>=0; idx-- )); do
    local digit=${digits:idx:1}
    outputs+=("$(interpret_digit "${digit}")")
  done
  local IFS=' → '
  printf '%s' "${outputs[*]}"
}

show_current() {
  local cfg
  cfg=$(read_config)
  local current_order current_pcie
  current_order=$(printf '%s\n' "${cfg}" | grep -E '^BOOT_ORDER=' | tail -n1 | cut -d'=' -f2- || true)
  current_pcie=$(printf '%s\n' "${cfg}" | grep -E '^PCIE_' || true)
  if [[ -n "${current_order}" ]]; then
    local interpretation
    interpretation=$(print_interpretation "${current_order}")
    printf '[boot-order] Current BOOT_ORDER=%s (%s)\n' "${current_order}" "${interpretation}"
  else
    printf '[boot-order] Current BOOT_ORDER not set\n'
  fi
  if [[ -n "${current_pcie}" ]]; then
    while IFS= read -r line; do
      printf '[boot-order] %s\n' "${line}"
    done <<<"${current_pcie}"
  fi
}

ensure_order() {
  local desired=$(sanitize_hex "$1")
  local tmpdir
  tmpdir=$(mktemp -d)
  trap 'rm -rf "${tmpdir}"' EXIT
  local current_cfg="${tmpdir}/current.conf"
  local target_cfg="${tmpdir}/target.conf"
  read_config >"${current_cfg}"
  cp "${current_cfg}" "${target_cfg}"
  if grep -q '^BOOT_ORDER=' "${target_cfg}"; then
    sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=${desired}/" "${target_cfg}"
  else
    printf '\nBOOT_ORDER=%s\n' "${desired}" >>"${target_cfg}"
  fi
  if [[ "${PCIE_PROBE:-}" == "1" ]]; then
    printf '[boot-order] Requesting PCIE_PROBE=1\n'
    if grep -q '^PCIE_PROBE=' "${target_cfg}"; then
      sed -i 's/^PCIE_PROBE=.*/PCIE_PROBE=1/' "${target_cfg}"
    else
      printf '\nPCIE_PROBE=1\n' >>"${target_cfg}"
    fi
  fi
  if cmp -s "${current_cfg}" "${target_cfg}"; then
    local interpretation
    interpretation=$(print_interpretation "${desired}")
    printf '[boot-order] BOOT_ORDER already %s (%s)\n' "${desired}" "${interpretation}"
  else
    local interpretation
    interpretation=$(print_interpretation "${desired}")
    printf '[boot-order] Applying BOOT_ORDER=%s (%s)\n' "${desired}" "${interpretation}"
    write_config "${target_cfg}"
  fi
  show_current
  rm -rf "${tmpdir}"
  trap - EXIT
}

case "${command_name}" in
  ensure_order)
    if [[ -z "${hex}" ]]; then
      echo "[boot-order] ensure_order requires a hex value" >&2
      exit 1
    fi
    ensure_order "${hex}"
    ;;
  print)
    show_current
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
