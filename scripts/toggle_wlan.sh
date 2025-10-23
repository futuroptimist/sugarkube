#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}" 
if [ -z "${MODE}" ]; then
  echo "Usage: toggle_wlan.sh --down|--restore" >&2
  exit 2
fi

WLAN_IF="${SUGARKUBE_WLAN_INTERFACE:-wlan0}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/toggle_wlan.log"
RUN_DIR="${SUGARKUBE_RUN_DIR:-/run/sugarkube}"
GUARD_FILE="${RUN_DIR}/wlan-disabled"

mkdir -p "${LOG_DIR}"
mkdir -p "${RUN_DIR}"

action_log() {
  local ts
  ts="$(date +'%Y-%m-%dT%H:%M:%S%z')"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}"
}

interface_exists() {
  ip link show "${WLAN_IF}" >/dev/null 2>&1
}

case "${MODE}" in
  --down)
    if ! interface_exists; then
      action_log "Interface ${WLAN_IF} not present; skipping shutdown"
      exit 0
    fi
    if [ -f "${GUARD_FILE}" ]; then
      action_log "Guard ${GUARD_FILE} already present; ${WLAN_IF} assumed down"
      exit 0
    fi
    if ip link set "${WLAN_IF}" down; then
      action_log "Brought ${WLAN_IF} down"
      touch "${GUARD_FILE}"
    else
      action_log "Failed to bring ${WLAN_IF} down"
      exit 1
    fi
    ;;
  --restore|--up)
    if [ ! -f "${GUARD_FILE}" ]; then
      action_log "No guard file at ${GUARD_FILE}; nothing to restore"
      exit 0
    fi
    if ! interface_exists; then
      action_log "Interface ${WLAN_IF} missing; removing guard"
      rm -f "${GUARD_FILE}"
      exit 0
    fi
    if ip link set "${WLAN_IF}" up; then
      action_log "Brought ${WLAN_IF} up"
      rm -f "${GUARD_FILE}"
    else
      action_log "Failed to bring ${WLAN_IF} up"
      exit 1
    fi
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    echo "Usage: toggle_wlan.sh --down|--restore" >&2
    exit 2
    ;;
esac

action_log "toggle_wlan.sh completed"
