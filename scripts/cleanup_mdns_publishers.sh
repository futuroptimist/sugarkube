#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENV="${SUGARKUBE_ENV:-dev}"
MDNS_RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
DRY_RUN="${DRY_RUN:-0}"

log() {
  echo "[cleanup-mdns] $*"
}

killed_any=0
for phase in bootstrap server; do
  pid_file="${MDNS_RUNTIME_DIR}/mdns-${CLUSTER}-${ENV}-${phase}.pid"
  if [ -f "${pid_file}" ]; then
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
      if [ "${DRY_RUN}" = "1" ]; then
        log "DRY_RUN=1: would kill ${phase} publisher pid=${pid}"
      else
        log "killing ${phase} publisher pid=${pid}"
        kill "${pid}" 2>/dev/null || true
        sleep 0.1
        if kill -0 "${pid}" 2>/dev/null; then
          log "force killing ${phase} publisher pid=${pid}"
          kill -9 "${pid}" 2>/dev/null || true
        fi
      fi
      killed_any=1
    fi
    if [ "${DRY_RUN}" = "1" ]; then
      log "DRY_RUN=1: would remove pid file ${pid_file}"
    else
      rm -f "${pid_file}"
    fi
    killed_any=1
  fi
done

svc="_k3s-${CLUSTER}-${ENV}._tcp"
if pgrep -af "avahi-publish.*${svc}" >/dev/null 2>&1; then
  if [ "${DRY_RUN}" = "1" ]; then
    log "DRY_RUN=1: would pkill stray avahi-publish for ${svc}"
  else
    log "pkill stray avahi-publish for ${svc}"
    pkill -f "avahi-publish.*${svc}" 2>/dev/null || true
  fi
  killed_any=1
fi

if command -v avahi-browse >/dev/null 2>&1; then
  if avahi-browse -pt "${svc}" 2>/dev/null | grep -q "${svc}"; then
    log "WARNING: advert for ${svc} still visible (browser cache may lag)"
  fi
fi

if [ "${killed_any}" = 1 ]; then
  if [ "${DRY_RUN}" = "1" ]; then
    log "DRY_RUN=1: dynamic publishers would be terminated"
  else
    log "dynamic publishers terminated"
  fi
fi
