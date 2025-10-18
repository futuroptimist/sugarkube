#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

EDITOR_BIN=${EDITOR:-nano}
RECOMMENDED_BOOT_ORDER=${RECOMMENDED_BOOT_ORDER:-0xF416}
SKIP_EDIT=${SKIP_EDIT:-0}

log() {
  printf '[finalize-nvme] %s\n' "$*"
}

fail() {
  printf '[finalize-nvme] error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command '$1' is missing"
  fi
}

require_cmd rpi-eeprom-config

current_config=$(rpi-eeprom-config 2>/dev/null || true)
if [[ -z "$current_config" ]]; then
  fail "Unable to read EEPROM configuration via rpi-eeprom-config"
fi

current_boot_order=$(awk -F '=' '/^BOOT_ORDER=/ {gsub("[[:space:]]", "", $2); print $2}' <<<"$current_config" | tail -n1)

printf '\n[finalize-nvme] Raspberry Pi bootloader summary\n'
printf '  Current BOOT_ORDER:    %s\n' "${current_boot_order:-unknown}"
printf '  Recommended order:     %s (NVMe → USB → SD → repeat)\n' "$RECOMMENDED_BOOT_ORDER"
printf '  Inspect command:       sudo rpi-eeprom-config\n'
printf '  Edit command:          sudo EDITOR=%s rpi-eeprom-config --edit\n' "$EDITOR_BIN"
printf '  Confirmation command:  sudo rpi-eeprom-update\n'

if [[ -z "$current_boot_order" ]]; then
  fail "BOOT_ORDER entry not found in EEPROM configuration"
fi

if [[ "${current_boot_order,,}" == "${RECOMMENDED_BOOT_ORDER,,}" ]]; then
  log "BOOT_ORDER already prioritizes NVMe/USB before SD. No edit required."
  exit 0
fi

log "BOOT_ORDER differs from recommended value."
log "Review the config, ensure BOOT_ORDER=${RECOMMENDED_BOOT_ORDER}, then save and exit."

if [[ "$SKIP_EDIT" == "1" ]]; then
  log "SKIP_EDIT=1 set; not launching editor."
  exit 0
fi

wrapper=$(mktemp)
cleanup() {
  rm -f "$wrapper"
}
trap cleanup EXIT

cat >"$wrapper" <<WRAP
#!/usr/bin/env bash
cat <<'INSTRUCTIONS'
########################################################################
# Update BOOT_ORDER so NVMe (0x4) and USB (0x1) are checked before SD.  #
# Recommended value: ${RECOMMENDED_BOOT_ORDER}                               #
# Save and exit to apply, or quit without saving to keep current order. #
########################################################################
INSTRUCTIONS
exec "$EDITOR_BIN" "$@"
WRAP
chmod +x "$wrapper"

EDITOR="$wrapper" rpi-eeprom-config --edit

log "After saving, run: sudo rpi-eeprom-update && sudo reboot"
