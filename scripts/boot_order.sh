#!/usr/bin/env bash
# Purpose: Inspect or enforce Raspberry Pi EEPROM boot order presets.
# Usage:
#   sudo scripts/boot_order.sh ensure_order 0xf461
#   sudo scripts/boot_order.sh print
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  boot_order.sh ensure_order <hex>
  boot_order.sh print

Examples:
  sudo boot_order.sh ensure_order 0xf461
  boot_order.sh print
USAGE
}

require_commands() {
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Missing required command: $cmd" >&2
      exit 1
    fi
  done
}

normalize_hex() {
  local input="$1"
  input=${input^^}
  if [[ $input != 0X* ]]; then
    input="0x${input}"
  fi
  echo "$input"
}

describe_nibble() {
  case "$1" in
    0) echo "retry" ;;
    1) echo "SD" ;;
    2) echo "network" ;;
    3) echo "USB (bootrom)" ;;
    4) echo "USB" ;;
    5) echo "reserved" ;;
    6) echo "NVMe" ;;
    7) echo "eMMC" ;;
    8) echo "USB (alt)" ;;
    9) echo "EEPROM" ;;
    A) echo "SD (safe)" ;;
    B) echo "stop" ;;
    C) echo "shutdown" ;;
    D) echo "restart" ;;
    E) echo "reserved" ;;
    F) echo "repeat" ;;
    *) echo "0x$1" ;;
  esac
}

human_readable_order() {
  local hex="$1"
  local trimmed=${hex#0x}
  trimmed=${trimmed^^}
  local length=${#trimmed}
  local parts=()
  for ((i=length-1; i>=0; i--)); do
    parts+=("$(describe_nibble "${trimmed:i:1}")")
  done
  if ((${#parts[@]} == 0)); then
    echo "n/a"
    return
  fi
  local joined
  printf -v joined '%s → ' "${parts[@]}"
  # remove trailing arrow and space
  echo "${joined% → }"
}

print_effective() {
  local current
  if ! current=$(rpi-eeprom-config 2>/dev/null); then
    echo "Failed to read EEPROM configuration" >&2
    exit 1
  fi
  local boot_order
  boot_order=$(grep -E '^BOOT_ORDER=' <<<"$current" | tail -n1 | cut -d'=' -f2 || true)
  if [[ -z "$boot_order" ]]; then
    echo "BOOT_ORDER is not set in EEPROM configuration" >&2
    exit 1
  fi
  boot_order=$(normalize_hex "$boot_order")
  echo "BOOT_ORDER=${boot_order} ($(human_readable_order "$boot_order"))"
  local pcie_lines
  pcie_lines=$(grep -E '^PCIE_' <<<"$current" || true)
  if [[ -n "$pcie_lines" ]]; then
    echo "$pcie_lines"
  fi
}

ensure_order() {
  local desired_hex
  desired_hex=$(normalize_hex "$1")
  require_commands rpi-eeprom-config mktemp cmp
  if [[ ${EUID} -ne 0 ]]; then
    echo "This command must be run as root (sudo)." >&2
    exit 1
  fi
  local tmp_dir
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "${tmp_dir}"' EXIT
  local current_conf="${tmp_dir}/current.conf"
  local target_conf="${tmp_dir}/boot.conf"
  if ! rpi-eeprom-config >"${current_conf}"; then
    echo "Failed to read current EEPROM configuration" >&2
    exit 1
  fi
  cp "${current_conf}" "${target_conf}"
  if grep -q '^BOOT_ORDER=' "${target_conf}"; then
    sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=${desired_hex}/" "${target_conf}"
  else
    printf '\nBOOT_ORDER=%s\n' "${desired_hex}" >>"${target_conf}"
  fi
  if [[ ${PCIE_PROBE:-} == 1 ]]; then
    if grep -q '^PCIE_PROBE=' "${target_conf}"; then
      sed -i 's/^PCIE_PROBE=.*/PCIE_PROBE=1/' "${target_conf}"
    else
      printf '\nPCIE_PROBE=1\n' >>"${target_conf}"
    fi
  fi
  if cmp -s "${current_conf}" "${target_conf}"; then
    echo "BOOT_ORDER already set to ${desired_hex} ($(human_readable_order "${desired_hex}")); no changes applied."
  else
    echo "Applying EEPROM boot configuration: BOOT_ORDER=${desired_hex} ($(human_readable_order "${desired_hex}"))"
    if ! rpi-eeprom-config --apply "${target_conf}"; then
      echo "Failed to apply EEPROM configuration" >&2
      exit 1
    fi
  fi
  print_effective
}

main() {
  if [[ $# -lt 1 ]]; then
    usage >&2
    exit 1
  fi
  case "$1" in
    ensure_order)
      if [[ $# -ne 2 ]]; then
        usage >&2
        exit 1
      fi
      ensure_order "$2"
      ;;
    print)
      require_commands rpi-eeprom-config
      print_effective
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
