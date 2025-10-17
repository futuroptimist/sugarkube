#!/usr/bin/env bash
# Deprecated stub: prefer scripts/boot_order.sh via `just boot-order nvme-first`.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BOOT_ORDER_SCRIPT="${SCRIPT_DIR}/boot_order.sh"

if [[ ! -x "${BOOT_ORDER_SCRIPT}" ]]; then
  echo "Missing helper: ${BOOT_ORDER_SCRIPT}" >&2
  exit 1
fi

echo "[deprecated] eeprom-nvme-first is deprecated and will be removed in a future release."
echo "[deprecated] Redirecting to BOOT_ORDER=0xf416 (NVMe → SD → USB → repeat)."
exec "${BOOT_ORDER_SCRIPT}" ensure_order 0xf416
