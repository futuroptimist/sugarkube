#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[finalize-nvme] %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Required command '$1' not found."
    exit 1
  fi
}

human_boot_order() {
  local order="${1,,}"
  case "${order}" in
    0xf416)
      echo "NVMe → SD → USB → repeat"
      ;;
    0xf461)
      echo "SD → NVMe → USB → repeat"
      ;;
    *)
      echo "Boot order ${1}"
      ;;
  esac
}

require_command rpi-eeprom-config

current_config=$(rpi-eeprom-config 2>/dev/null || true)
if [[ -z "${current_config}" ]]; then
  log "Unable to read current EEPROM configuration."
  log "Ensure this command is run on a Raspberry Pi 4/5 with rpi-eeprom-config installed."
  exit 1
fi

current_order=$(printf '%s\n' "${current_config}" | awk -F= '/^BOOT_ORDER=/ {print $2}' | tr -d '[:space:]')
current_order=${current_order:-unknown}
recommended_order="0xF416"

log "Current BOOT_ORDER: ${current_order} ($(human_boot_order "${current_order}"))"
log "Recommended NVMe-first order: ${recommended_order} ($(human_boot_order "${recommended_order}"))"

if [[ "${current_order^^}" == "${recommended_order^^}" ]]; then
  log "EEPROM already prioritizes NVMe/USB before SD."
  log "Confirm anytime with: sudo rpi-eeprom-config | grep BOOT_ORDER"
  exit 0
fi

log "NVMe boot requires BOOT_ORDER=${recommended_order}. This keeps the SD card available as a fallback."
log "Launching rpi-eeprom-config --edit so you can update BOOT_ORDER manually."

editor_real=${EDITOR:-nano}
wrapper=$(mktemp)
cat <<'WRAP' >"${wrapper}"
#!/usr/bin/env bash
set -Eeuo pipefail
cat <<'MSG'
# Sugarkube finalize-nvme guidance
# 1. Locate the BOOT_ORDER line and set it to 0xF416 (NVMe → SD → USB → repeat).
# 2. Save and exit to let rpi-eeprom-config apply the change.
# 3. Confirm afterwards with: sudo rpi-eeprom-config | grep BOOT_ORDER
MSG
exec "${FINALIZE_NVME_EDITOR_REAL}" "$@"
WRAP
chmod +x "${wrapper}"
trap 'rm -f "${wrapper}"' EXIT

FINALIZE_NVME_EDITOR_REAL="${editor_real}" EDITOR="${wrapper}" rpi-eeprom-config --edit

updated_config=$(rpi-eeprom-config 2>/dev/null || true)
updated_order=$(printf '%s\n' "${updated_config}" | awk -F= '/^BOOT_ORDER=/ {print $2}' | tr -d '[:space:]')
updated_order=${updated_order:-unknown}

log "Updated BOOT_ORDER: ${updated_order} ($(human_boot_order "${updated_order}"))"
log "Reboot when ready and verify with 'sudo rpi-eeprom-config | grep BOOT_ORDER'."
