#!/usr/bin/env bash
set -euo pipefail

THRESHOLD_MS=${SUGARKUBE_TIME_OFFSET_MAX_MS:-500}
CHRONY_BIN="${SUGARKUBE_CHRONYC_BIN:-chronyc}"
TIMESYNC_SERVICE="${SUGARKUBE_TIMESYNC_SERVICE:-systemd-timesyncd.service}"

log() {
  local level="$1"
  shift
  printf '%s: %s\n' "${level}" "$*" >&2
}

python_abs_ms() {
  python3 - "$@" <<'PY'
import sys
from decimal import Decimal

def abs_ms(value):
    try:
        dec = Decimal(value)
    except Exception:
        return None
    return abs(dec) * Decimal('1000')

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("", end="")
        raise SystemExit(0)
    result = abs_ms(sys.argv[1])
    if result is None:
        print("", end="")
    else:
        print(format(result.normalize(), 'f'))
PY
}

check_chrony() {
  local tracking_output=""
  local status=0
  set +e
  tracking_output="$(${CHRONY_BIN} tracking 2>&1)"
  status=$?
  set -e
  if [ "${status}" -ne 0 ]; then
    log "error" "chronyc tracking failed (${status}): ${tracking_output}"
    return 2
  fi

  local last_offset
  last_offset="$(printf '%s\n' "${tracking_output}" | awk -F': *' '/^Last offset/ {print $2}' | awk '{print $1}' | tail -n1)"
  if [ -z "${last_offset}" ]; then
    last_offset="$(printf '%s\n' "${tracking_output}" | awk -F': *' '/^System time/ {print $2}' | awk '{print $1}' | tail -n1)"
  fi

  if [ -z "${last_offset}" ]; then
    log "error" "Unable to parse offset from chronyc output"
    return 2
  fi

  local abs_offset_ms
  abs_offset_ms="$(python_abs_ms "${last_offset}")"
  if [ -z "${abs_offset_ms}" ]; then
    log "error" "Failed to interpret chronyc offset '${last_offset}'"
    return 2
  fi

  local compare_ms
  compare_ms="$(python3 - <<'PY'
import sys
from decimal import Decimal
value = Decimal(sys.argv[1])
threshold = Decimal(sys.argv[2])
print(int(value > threshold))
PY
"${abs_offset_ms}" "${THRESHOLD_MS}")"

  log "info" "chrony offset=${abs_offset_ms}ms threshold=${THRESHOLD_MS}ms"

  if [ "${compare_ms}" -eq 0 ]; then
    return 0
  fi

  if [ "${SUGARKUBE_FIX_TIME:-0}" = "1" ]; then
    log "warn" "Offset exceeds threshold; attempting chronyc -a makestep"
    if ${CHRONY_BIN} -a makestep >/dev/null 2>&1; then
      log "info" "chronyc makestep executed"
      return 0
    fi
    log "error" "chronyc makestep failed"
  else
    log "error" "Offset exceeds threshold and SUGARKUBE_FIX_TIME!=1"
  fi
  return 1
}

parse_timesyncd_last_success() {
  local status_output="$1"
  printf '%s' "${status_output}" | awk -F': ' '/^Last Successful Update/ {print $2}' | tail -n1
}

check_timesyncd() {
  if ! command -v systemctl >/dev/null 2>&1; then
    log "error" "systemctl is unavailable to inspect time sync"
    return 2
  fi

  if ! systemctl is-active --quiet "${TIMESYNC_SERVICE}"; then
    log "error" "${TIMESYNC_SERVICE} is not active"
    return 1
  fi

  local sync_state
  sync_state="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || timedatectl show -p SystemClockSynchronized --value 2>/dev/null || echo "")"
  if [ "${sync_state}" != "yes" ]; then
    log "error" "System clock is not synchronized (NTPSynchronized=${sync_state})"
    return 1
  fi

  local timesync_status
  local status_code=0
  set +e
  timesync_status="$(timedatectl timesync-status 2>/dev/null)"
  status_code=$?
  set -e
  if [ "${status_code}" -eq 0 ] && [ -n "${timesync_status}" ]; then
    local last_success
    last_success="$(parse_timesyncd_last_success "${timesync_status}")"
    if [ -n "${last_success}" ] && [ "${last_success}" != "n/a" ]; then
      if command -v date >/dev/null 2>&1; then
        local last_epoch
        last_epoch="$(date -d "${last_success}" +%s 2>/dev/null || true)"
        if [ -n "${last_epoch}" ]; then
          local now_epoch
          now_epoch="$(date -u +%s)"
          local max_age="${SUGARKUBE_TIMESYNC_MAX_AGE:-600}"
          if [ $((now_epoch - last_epoch)) -gt "${max_age}" ]; then
            log "error" "Last successful sync at ${last_success} exceeds allowed age ${max_age}s"
            return 1
          fi
        fi
      fi
    fi
  fi

  log "info" "systemd-timesyncd active and synchronized"
  return 0
}

main() {
  if ! command -v python3 >/dev/null 2>&1; then
    log "error" "python3 is required to evaluate time synchronization"
    return 2
  fi

  if command -v "${CHRONY_BIN}" >/dev/null 2>&1; then
    check_chrony
    return $?
  fi

  if command -v timedatectl >/dev/null 2>&1; then
    check_timesyncd
    return $?
  fi

  log "error" "No supported time synchronization mechanism detected"
  return 1
}

main "$@"
