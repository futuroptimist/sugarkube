#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RECOMMENDED_ORDER=0xF416
FINALIZE_NVME_EDIT=${FINALIZE_NVME_EDIT:-1}
EDITOR_CMD=${EDITOR:-nano}

log() {
  printf '[finalize-nvme] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1"
    exit 1
  fi
}

require_cmd rpi-eeprom-config
require_cmd awk

read_boot_order() {
  local output
  if ! output=$(rpi-eeprom-config --config 2>/dev/null); then
    log "Unable to read EEPROM configuration"
    exit 1
  fi
  printf '%s\n' "$output" | awk -F= '/^BOOT_ORDER/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}' | tail -n1
}

normalize_order() {
  local raw=$1
  raw=${raw^^}
  if [[ "$raw" =~ ^0X[0-9A-F]+$ ]]; then
    printf '%s\n' "$raw"
  elif [[ "$raw" =~ ^[0-9]+$ ]]; then
    printf '0x%X\n' "$raw"
  else
    printf '%s\n' "$raw"
  fi
}

current_raw=$(read_boot_order)
if [ -z "$current_raw" ]; then
  log "BOOT_ORDER not found in EEPROM configuration"
  exit 1
fi

current_order=$(normalize_order "$current_raw")
recommended=$(normalize_order "$RECOMMENDED_ORDER")

printf '\n=== Raspberry Pi NVMe Finalization ===\n'
printf 'Current BOOT_ORDER : %s\n' "$current_order"
printf 'Recommended order : %s (NVMe → USB → SD → repeat)\n' "$recommended"
printf '\nUse this command to inspect later:\n'
printf '  sudo rpi-eeprom-config --config | grep BOOT_ORDER\n'

if [ "$current_order" = "$recommended" ]; then
  printf '\nBOOT_ORDER already prefers NVMe. No changes required.\n'
  printf '\nExpected output:\n'
  printf '  [ok] BOOT_ORDER=0xF416\n'
  printf '  [ok] NVMe/USB precede SD in the boot sequence\n'
  exit 0
fi

printf '\nThe recommended sequence ensures NVMe is attempted before the SD card.\n'
printf 'Review the EEPROM configuration and update BOOT_ORDER to %s if appropriate.\n' "$recommended"
printf '\nTo edit safely, update the BOOT_ORDER line to %s and save the file.\n' "$recommended"
printf 'Changes apply after a reboot.\n'

if [ "$FINALIZE_NVME_EDIT" = "0" ]; then
  printf '\nFINALIZE_NVME_EDIT=0 set; skipping editor launch.\n'
  printf 'Run manually when ready:\n  sudo -E rpi-eeprom-config --edit\n'
  exit 0
fi

printf '\nLaunching rpi-eeprom-config --edit using %s...\n' "$EDITOR_CMD"
printf 'Look for BOOT_ORDER and set it to %s (NVMe → USB → SD → repeat).\n' "$recommended"
printf 'After saving, reboot and confirm with: sudo rpi-eeprom-config --config | grep BOOT_ORDER\n'

EDITOR="$EDITOR_CMD" rpi-eeprom-config --edit
