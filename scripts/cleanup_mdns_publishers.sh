#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENV="${SUGARKUBE_ENV:-dev}"

log() { echo "[cleanup-mdns] $*"; }

svc="_k3s-${CLUSTER}-${ENV}._tcp"

if [ "${DRY_RUN}" = "1" ]; then
  log "DRY_RUN=1: would clean dynamic publishers for ${svc}"
  exit 0
fi

wait_for_pid_exit() {
  local target="$1"
  local attempts=0
  while [ "${attempts}" -lt 50 ]; do
    if ! kill -0 "${target}" 2>/dev/null; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 0.1
  done
  return 1
}

wait_for_pattern_absence() {
  local pattern="$1"
  local attempts=0
  while [ "${attempts}" -lt 50 ]; do
    if ! pgrep -af "${pattern}" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 0.1
  done
  return 1
}

killed_any=0
for phase in bootstrap server; do
  PF="/run/sugarkube/mdns-${CLUSTER}-${ENV}-${phase}.pid"
  if [ -f "${PF}" ]; then
    PID="$(cat "${PF}" 2>/dev/null || true)"
    if [ -n "${PID:-}" ] && kill -0 "${PID}" 2>/dev/null; then
      log "killing ${phase} publisher pid=${PID}"
      kill "${PID}" 2>/dev/null || true
      if ! wait_for_pid_exit "${PID}"; then
        log "WARNING: pid ${PID} still running after termination request; sending SIGKILL"
        kill -9 "${PID}" 2>/dev/null || true
        if ! wait_for_pid_exit "${PID}"; then
          log "WARNING: pid ${PID} persisted after SIGKILL"
        fi
      fi
      killed_any=1
    fi
    rm -f "${PF}"
  fi
done

if pgrep -af "avahi-publish-service.*${svc}" >/dev/null 2>&1; then
  log "pkill stray avahi-publish-service for ${svc}"
  pkill -f "avahi-publish-service.*${svc}" 2>/dev/null || true
  if ! wait_for_pattern_absence "avahi-publish-service.*${svc}"; then
    log "WARNING: avahi-publish-service processes for ${svc} still present; sending SIGKILL"
    pkill -9 -f "avahi-publish-service.*${svc}" 2>/dev/null || true
    if ! wait_for_pattern_absence "avahi-publish-service.*${svc}"; then
      log "WARNING: avahi-publish-service processes for ${svc} persisted after SIGKILL"
    fi
  fi
  killed_any=1
fi

if command -v avahi-browse >/dev/null 2>&1; then
  if avahi-browse -pt "${svc}" 2>/dev/null | grep -q "${svc}"; then
    log "WARNING: advert for ${svc} still visible (browser cache may lag)"
  fi
fi

if [ "${killed_any}" = 1 ]; then
  log "dynamic publishers terminated"
fi
