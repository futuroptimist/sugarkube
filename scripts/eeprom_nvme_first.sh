#!/usr/bin/env bash
# Deprecated wrapper for the old eeprom-nvme-first helper.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ORDER_HEX="0xf416"

cat <<'MSG'
[eeprom] WARNING: eeprom-nvme-first is deprecated and will be removed in a future release.
[eeprom] It now delegates to 'just boot-order nvme-first' to apply BOOT_ORDER=0xf416 (NVMe → SD → USB → repeat).
[eeprom] Update your automation to call the new boot-order target directly.
MSG

"${SCRIPT_DIR}/boot_order.sh" ensure_order "${ORDER_HEX}"
