#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/toggle_wlan.log"
RUN_DIR="${SUGARKUBE_RUN_DIR:-/run/sugarkube}"
WLAN_IFACE="${SUGARKUBE_WLAN_INTERFACE:-wlan0}"
GUARD_FILE="${RUN_DIR}/wlan-disabled"

log() {
  local ts
  ts="$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  mkdir -p "${LOG_DIR}"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

interface_exists() {
  ip link show "${WLAN_IFACE}" >/dev/null 2>&1
}

bring_down() {
  if ! interface_exists; then
    log "Interface ${WLAN_IFACE} not present; skipping disable"
    return 0
  fi
  mkdir -p "${RUN_DIR}"
  if [ -f "${GUARD_FILE}" ]; then
    log "Guard ${GUARD_FILE} already present; ${WLAN_IFACE} assumed down"
  fi
  log "Bringing ${WLAN_IFACE} down"
  ip link set "${WLAN_IFACE}" down || log "Failed to bring ${WLAN_IFACE} down"
  : >"${GUARD_FILE}"
}

restore() {
  if [ ! -f "${GUARD_FILE}" ]; then
    log "Guard ${GUARD_FILE} missing; nothing to restore"
    return 0
  fi
  if ! interface_exists; then
    log "Interface ${WLAN_IFACE} not present; cannot restore"
    rm -f "${GUARD_FILE}"
    return 0
  fi
  log "Restoring ${WLAN_IFACE}"
  ip link set "${WLAN_IFACE}" up || {
    log "Failed to bring ${WLAN_IFACE} up";
    return 1;
  }
  rm -f "${GUARD_FILE}"
}

usage() {
  cat <<'EOF_USAGE'
Usage: toggle_wlan.sh --down|--restore

  --down     Bring the WLAN interface down and record guard file.
  --restore  Bring the WLAN interface up when the guard file exists.
EOF_USAGE
}

main() {
  if [ $# -ne 1 ]; then
    usage >&2
    exit 2
  fi

  if ! command -v ip >/dev/null 2>&1; then
    log "ip command not available; skipping"
    exit 0
  fi

  case "$1" in
    --down)
      bring_down
      ;;
    --restore)
      restore
      ;;
    --help|-h)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
