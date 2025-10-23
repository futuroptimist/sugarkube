#!/usr/bin/env bash
set -euo pipefail

WLAN_IFACE="${SUGARKUBE_WLAN_INTERFACE:-wlan0}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/toggle_wlan.log"
RUN_DIR="${SUGARKUBE_RUN_DIR:-/run/sugarkube}"
GUARD_FILE="${SUGARKUBE_WLAN_GUARD:-${RUN_DIR}/wlan-disabled}"

log() {
  local timestamp
  timestamp="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf '%s %s\n' "${timestamp}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

usage() {
  cat <<'USAGE'
Usage: toggle_wlan.sh [--down|--restore]

  --down     Bring the wireless interface down and mark it disabled.
  --restore  Bring the interface back up when previously disabled.
USAGE
}

ensure_tools() {
  if ! command -v ip >/dev/null 2>&1; then
    log "ip command not available; skipping wlan toggle"
    return 1
  fi
  return 0
}

bring_down() {
  if ! ensure_tools; then
    return 0
  fi
  if ! ip link show "${WLAN_IFACE}" >/dev/null 2>&1; then
    log "Interface ${WLAN_IFACE} not found; nothing to disable"
    return 0
  fi
  if ip link show "${WLAN_IFACE}" | grep -q "state DOWN"; then
    log "${WLAN_IFACE} already down"
  else
    if ip link set "${WLAN_IFACE}" down; then
      log "Brought ${WLAN_IFACE} down"
    else
      log "Failed to bring ${WLAN_IFACE} down"
      return 1
    fi
  fi
  mkdir -p "${RUN_DIR}"
  if [ ! -f "${GUARD_FILE}" ]; then
    touch "${GUARD_FILE}"
    log "Created guard ${GUARD_FILE}"
  else
    log "Guard ${GUARD_FILE} already present"
  fi
  return 0
}

restore_iface() {
  if [ ! -f "${GUARD_FILE}" ]; then
    log "Guard ${GUARD_FILE} missing; nothing to restore"
    return 0
  fi
  if ! ensure_tools; then
    rm -f "${GUARD_FILE}"
    return 0
  fi
  if ! ip link show "${WLAN_IFACE}" >/dev/null 2>&1; then
    log "Interface ${WLAN_IFACE} not found during restore"
    rm -f "${GUARD_FILE}"
    return 0
  fi
  if ip link set "${WLAN_IFACE}" up; then
    log "Brought ${WLAN_IFACE} up"
  else
    log "Failed to bring ${WLAN_IFACE} up"
    return 1
  fi
  rm -f "${GUARD_FILE}"
  log "Removed guard ${GUARD_FILE}"
  return 0
}

ACTION=""
if [ "$#" -gt 0 ]; then
  case "$1" in
    --down)
      ACTION="down"
      ;;
    --restore)
      ACTION="restore"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
fi

if [ -z "${ACTION}" ]; then
  usage >&2
  exit 2
fi

mkdir -p "${LOG_DIR}"

case "${ACTION}" in
  down)
    bring_down
    ;;
  restore)
    restore_iface
    ;;
esac
