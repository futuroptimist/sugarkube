#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[finalize-nvme] %s\n' "$*"
}

fail() {
  local reason="$1"
  local next="$2"
  printf 'finalize-nvme: %s. Next: %s\n' "$reason" "$next" >&2
  exit 1
}

require_cmd() {
  local binary="$1"
  if ! command -v "$binary" >/dev/null 2>&1; then
    fail "missing required command '$binary'" "sudo apt-get install -y rpi-eeprom"
  fi
}

parse_boot_order() {
  awk -F'=' 'toupper($1)=="BOOT_ORDER" {print toupper($2); exit}'
}

human_order() {
  local value="$1"
  case "${value,,}" in
    0xf416)
      echo "NVMe → USB → SD → repeat"
      ;;
    0xf461)
      echo "SD → NVMe → USB → repeat"
      ;;
    *)
      echo "Boot order ${value}"
      ;;
  esac
}

require_cmd rpi-eeprom-config

EDITOR_CMD="${EDITOR:-nano}"
RECOMMENDED="0xF416"

log "Reading current EEPROM boot configuration"
if ! config_output=$(rpi-eeprom-config 2>/dev/null); then
  fail "unable to read current EEPROM configuration" "sudo rpi-eeprom-config"
fi

current_order=$(printf '%s\n' "$config_output" | parse_boot_order)
if [[ -z "$current_order" ]]; then
  fail "BOOT_ORDER not found in EEPROM configuration" "sudo rpi-eeprom-config"
fi

log "Current BOOT_ORDER=${current_order} ($(human_order "$current_order"))"
log "Recommended BOOT_ORDER=${RECOMMENDED} ($(human_order "$RECOMMENDED"))"

if [[ "${current_order^^}" == "${RECOMMENDED}" ]]; then
  cat <<EOF
[finalize-nvme] No changes required.
  • BOOT_ORDER already prefers NVMe/USB before SD.
  • Confirm anytime with: sudo rpi-eeprom-config | grep BOOT_ORDER
EOF
  exit 0
fi

cat <<EOF
[finalize-nvme] Guidance
  • Save BOOT_ORDER=${RECOMMENDED} to prioritize NVMe boot.
  • The editor will open the EEPROM config; add or adjust BOOT_ORDER as noted.
  • Save and exit to apply, or cancel to abort.
EOF

wrapper=$(mktemp)
cleanup() {
  local status=$?
  rm -f "$wrapper"
  exit "$status"
}
trap cleanup EXIT

cat <<'SCRIPT' >"$wrapper"
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
cat <<'NOTE'
# --- sugarkube finalize-nvme guidance ---
# Ensure BOOT_ORDER=0xF416 (NVMe → USB → SD → repeat)
# Save and exit to apply. Cancel to leave EEPROM unchanged.
# ----------------------------------------
NOTE
exec ${REAL_EDITOR:-nano} "$@"
SCRIPT
chmod +x "$wrapper"

REAL_EDITOR="$EDITOR_CMD" EDITOR="$wrapper" rpi-eeprom-config --edit

log "Review complete. Re-run this command to confirm applied settings:"
log "  sudo rpi-eeprom-config | grep BOOT_ORDER"
