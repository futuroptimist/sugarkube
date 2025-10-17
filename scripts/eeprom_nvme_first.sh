#!/usr/bin/env bash
# Deprecated helper retained for a single release cycle.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo "[deprecated] 'scripts/eeprom_nvme_first.sh' will be removed in a future release." >&2
echo "[deprecated] Use 'just boot-order nvme-first' instead." >&2
echo "[deprecated] Applying BOOT_ORDER=0xF416 (NVMe → SD → USB → repeat)." >&2

"${SCRIPT_DIR}/boot_order.sh" ensure_order "0xF416"
