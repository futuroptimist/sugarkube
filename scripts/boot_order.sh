#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

main() {
  if [[ $# -lt 1 ]]; then
    usage >&2
    exit 1
  fi

  case "$1" in
    ensure_order)
      shift
      ensure_order "$@"
      ;;
    print)
      shift
      print_status "$@"
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
}

usage() {
  cat <<'USAGE'
Usage:
  boot_order.sh ensure_order <hex>  Set BOOT_ORDER to the specified hex value.
  boot_order.sh print               Show current BOOT_ORDER and PCIE_* keys.

Set PCIE_PROBE=1 in the environment to append PCIE_PROBE=1 when applying an order.
USAGE
}

require_binary() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[boot-order] Missing required command: $1" >&2
    exit 1
  fi
}

sudo_prefix() {
  if [[ ${EUID} -eq 0 ]]; then
    echo ""
  else
    echo "sudo"
  fi
}

ensure_order() {
  if [[ $# -ne 1 ]]; then
    echo "[boot-order] ensure_order expects exactly one argument (hex value)." >&2
    usage >&2
    exit 1
  fi

  local desired="$1"
  validate_hex "$desired"
  desired=$(normalize_hex "$desired")

  require_binary rpi-eeprom-config

  local sudo_cmd
  sudo_cmd=$(sudo_prefix)

  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "${tmp_dir}"' EXIT

  local current_conf="${tmp_dir}/current.conf"
  local target_conf="${tmp_dir}/target.conf"

  if ! ${sudo_cmd} rpi-eeprom-config >"${current_conf}"; then
    echo "[boot-order] Failed to read current EEPROM configuration." >&2
    exit 1
  fi

  cp "${current_conf}" "${target_conf}"

  update_key "${target_conf}" "BOOT_ORDER" "${desired}"

  if [[ "${PCIE_PROBE:-}" == "1" ]]; then
    update_key "${target_conf}" "PCIE_PROBE" "1"
  fi

  if cmp -s "${current_conf}" "${target_conf}"; then
    echo "[boot-order] BOOT_ORDER already set to ${desired} ($(describe_order "${desired}")); no changes needed."
    print_status
    return
  fi

  echo "[boot-order] Applying BOOT_ORDER=${desired} ($(describe_order "${desired}"))."
  ${sudo_cmd} rpi-eeprom-config --edit "${target_conf}"

  print_status
}

update_key() {
  local file="$1"
  local key="$2"
  local value="$3"

  if grep -qi "^${key}=" "${file}"; then
    sed -i "s/^${key}=.*/${key}=${value}/I" "${file}"
  else
    printf '\n%s=%s\n' "${key}" "${value}" >>"${file}"
  fi
}

validate_hex() {
  local value="$1"
  if [[ ! ${value} =~ ^0[xX][0-9a-fA-F]+$ ]]; then
    echo "[boot-order] Invalid hex value: ${value}. Expected format 0x####." >&2
    exit 1
  fi
}

normalize_hex() {
  local value="$1"
  printf '0x%s\n' "${value#0x}" | tr '[:lower:]' '[:upper:]'
}

print_status() {
  require_binary rpi-eeprom-config

  local sudo_cmd
  sudo_cmd=$(sudo_prefix)

  local config
  if ! config=$(${sudo_cmd} rpi-eeprom-config); then
    echo "[boot-order] Failed to read EEPROM configuration." >&2
    exit 1
  fi

  local order
  order=$(printf '%s\n' "${config}" | awk -F'=' 'toupper($1)=="BOOT_ORDER" {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit}')

  if [[ -z ${order} ]]; then
    echo "[boot-order] BOOT_ORDER not found in EEPROM configuration." >&2
    exit 1
  fi

  order=$(normalize_hex "${order}")
  echo "[boot-order] Current BOOT_ORDER=${order} ($(describe_order "${order}"))."

  local pcie
  pcie=$(printf '%s\n' "${config}" | grep -E '^PCIE_' || true)
  if [[ -n ${pcie} ]]; then
    echo "[boot-order] PCIE settings:\n${pcie}"
  else
    echo "[boot-order] No PCIE_* overrides set."
  fi
}

describe_order() {
  local order=$(printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]')
  order=${order#0x}
  if [[ -z ${order} ]]; then
    echo "unknown order"
    return
  fi

  local -a labels=()
  local -i idx
  for ((idx=${#order}-1; idx>=0; idx--)); do
    local nibble=${order:idx:1}
    labels+=("$(describe_nibble "${nibble}")")
  done

  local description="${labels[0]}"
  for ((idx=1; idx<${#labels[@]}; idx++)); do
    description+=" → ${labels[idx]}"
  done

  echo "${description}"
}

describe_nibble() {
  local nibble=$(printf '%s\n' "$1" | tr '[:lower:]' '[:upper:]')
  case "${nibble}" in
    0) echo "Stop" ;;
    1) echo "SD" ;;
    2) echo "Network" ;;
    3) echo "USB 2.0" ;;
    4) echo "USB" ;;
    5) echo "USB (retry)" ;;
    6) echo "NVMe" ;;
    7) echo "USB boot (type 7)" ;;
    8) echo "USB (type 8)" ;;
    9) echo "USB (type 9)" ;;
    A) echo "SD (alt)" ;;
    B) echo "Network (alt)" ;;
    C) echo "USB (type C)" ;;
    D) echo "USB (type D)" ;;
    E) echo "Retry" ;;
    F) echo "repeat" ;;
    *) echo "0x${nibble}" ;;
  esac
}

main "$@"
