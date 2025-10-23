#!/usr/bin/env bash
set -euo pipefail

MODE=""
WLAN_IFACE="${SUGARKUBE_WLAN_INTERFACE:-wlan0}"
RUN_DIR="${SUGARKUBE_RUN_DIR:-/run/sugarkube}"
GUARD_FILE="${RUN_DIR}/wlan-disabled"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/toggle_wlan.log"

log() {
  local timestamp
  timestamp="$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  local message="$*"
  printf '%s %s\n' "${timestamp}" "${message}"
  printf '%s %s\n' "${timestamp}" "${message}" >>"${LOG_FILE}"
}

usage() {
  cat <<'USAGE'
Usage: toggle_wlan.sh [--down|--restore]

  --down     Disable the wireless interface and record guard state.
  --restore  Re-enable the wireless interface if it was disabled by this script.
USAGE
}

parse_args() {
  if [ "$#" -eq 0 ]; then
    MODE="down"
    return
  fi

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --down)
        MODE="down"
        ;;
      --restore)
        MODE="restore"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf 'Unknown option: %s\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done
}

interface_exists() {
  ip link show "${WLAN_IFACE}" >/dev/null 2>&1
}

disable_wlan() {
  if ! interface_exists; then
    log "Interface ${WLAN_IFACE} not found; skipping disable"
    return 0
  fi

  mkdir -p "${RUN_DIR}"
  ip link set "${WLAN_IFACE}" down
  touch "${GUARD_FILE}"
  log "Brought ${WLAN_IFACE} down and recorded guard at ${GUARD_FILE}"
}

enable_wlan() {
  if [ ! -f "${GUARD_FILE}" ]; then
    log "Guard file ${GUARD_FILE} missing; nothing to restore"
    return 0
  fi

  if interface_exists; then
    ip link set "${WLAN_IFACE}" up
    log "Brought ${WLAN_IFACE} back up"
  else
    log "Interface ${WLAN_IFACE} missing during restore"
  fi

  rm -f "${GUARD_FILE}"
}

main() {
  mkdir -p "${LOG_DIR}"
  touch "${LOG_FILE}"
  parse_args "$@"

  case "${MODE}" in
    down)
      disable_wlan
      ;;
    restore)
      enable_wlan
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
