#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[rollback-plan] %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

root_source=$(findmnt -no SOURCE / 2>/dev/null || echo "unknown")
boot_order="unknown"
if require_command rpi-eeprom-config; then
  boot_order=$(rpi-eeprom-config 2>/dev/null | awk -F= '/^BOOT_ORDER=/ {print $2}' | tr -d '[:space:]')
  boot_order=${boot_order:-unknown}
fi

log "Current root filesystem source: ${root_source}"
log "Current EEPROM BOOT_ORDER: ${boot_order}"
log "The steps below prefer the SD card on the next boot without applying changes automatically."

cat <<'STEPS'
1) Preview the SD fallback changes (no modifications):
     sudo scripts/rollback_to_sd.sh --dry-run

2) Apply the cmdline.txt and fstab updates to point back to the SD card:
     sudo scripts/rollback_to_sd.sh

3) Prefer the SD card in the EEPROM boot order (Pi 4/5):
     sudo just boot-order sd-nvme-usb

4) Confirm the BOOT_ORDER and the updated files:
     sudo rpi-eeprom-config | grep BOOT_ORDER
     ls -lh /boot/cmdline.txt /etc/fstab

Reboot when ready. You can restore NVMe priority later with:
     sudo just finalize-nvme
STEPS
