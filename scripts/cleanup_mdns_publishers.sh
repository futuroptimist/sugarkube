#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"

log() {
  printf '[cleanup-mdns %s/%s] %s\n' "${CLUSTER}" "${ENVIRONMENT}" "$*"
}

maybe_remove_pid_file() {
  local phase="$1"
  local pid_file="$2"
  if [ "${DRY_RUN}" = "1" ]; then
    log "DRY_RUN=1: would remove ${pid_file}"
    return 0
  fi
  rm -f "${pid_file}" >/dev/null 2>&1 || true
}

maybe_kill_pid() {
  local phase="$1"
  local pid="$2"
  if [ "${DRY_RUN}" = "1" ]; then
    log "DRY_RUN=1: would kill ${phase} publisher pid=${pid}"
    return 1
  fi
  if kill -0 "${pid}" >/dev/null 2>&1; then
    log "killing ${phase} publisher pid=${pid}"
    kill "${pid}" >/dev/null 2>&1 || true
    return 0
  fi
  return 1
}

killed_any=0
if [ -d "${RUNTIME_DIR}" ]; then
  for phase in bootstrap server; do
    pid_file="${RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-${phase}.pid"
    if [ ! -f "${pid_file}" ]; then
      continue
    fi
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [ -z "${pid}" ]; then
      log "removing empty ${phase} pidfile"
      maybe_remove_pid_file "${phase}" "${pid_file}"
      continue
    fi
    if kill -0 "${pid}" >/dev/null 2>&1; then
      if maybe_kill_pid "${phase}" "${pid}"; then
        killed_any=1
      fi
    else
      log "removing stale ${phase} pidfile pid=${pid}"
    fi
    maybe_remove_pid_file "${phase}" "${pid_file}"
  done
else
  log "runtime dir ${RUNTIME_DIR} missing; skipping pidfile cleanup"
fi

svc="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
if pgrep -af "avahi-publish-service.*${svc}" >/dev/null 2>&1; then
  if [ "${DRY_RUN}" = "1" ]; then
    log "DRY_RUN=1: would pkill stray avahi-publish-service for ${svc}"
  else
    log "pkill stray avahi-publish-service for ${svc}"
    pkill -f "avahi-publish-service.*${svc}" >/dev/null 2>&1 || true
    killed_any=1
  fi
fi

if [ "${DRY_RUN}" != "1" ] && command -v avahi-browse >/dev/null 2>&1; then
  if avahi-browse -pt "${svc}" 2>/dev/null | grep -q "${svc}"; then
    log "WARNING: advert for ${svc} still visible (browser cache may lag)"
  fi
fi

if [ "${killed_any}" = "1" ]; then
  log "dynamic publishers terminated"
fi
