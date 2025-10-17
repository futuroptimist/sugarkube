#!/usr/bin/env bash
# Purpose: Map friendly boot-order presets to EEPROM hex values.
# Usage: sudo ./scripts/apply_boot_order_preset.sh sd-nvme-usb
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BOOT_ORDER_CMD=${BOOT_ORDER_CMD:-"${SCRIPT_DIR}/boot_order.sh"}

usage() {
  cat <<'USAGE'
Usage: apply_boot_order_preset.sh <preset>

Presets:
  sd-nvme-usb  SD → NVMe → USB → repeat (0xF461)
  nvme-first   NVMe → SD → USB → repeat (0xF416)
USAGE
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 1
fi

preset=$1
case "${preset}" in
  sd-nvme-usb)
    order="0xF461"
    human="SD → NVMe → USB → repeat"
    ;;
  nvme-first)
    order="0xF416"
    human="NVMe → SD → USB → repeat"
    ;;
  *)
    echo "Unknown boot-order preset '${preset}'. Use sd-nvme-usb or nvme-first." >&2
    exit 1
    ;;
esac

echo "[boot-order] Target preset '${preset}' => BOOT_ORDER=${order} (${human})."
"${BOOT_ORDER_CMD}" ensure_order "${order}"
