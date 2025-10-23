#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"

log() {
  printf '[cleanup-mdns] %s\n' "$*"
}

killed_any=0
for phase in bootstrap server; do
  pidfile="${RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-${phase}.pid"
  if [ -f "${pidfile}" ]; then
    pid="$(cat "${pidfile}" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
      log "killing ${phase} publisher pid=${pid}"
      kill "${pid}" 2>/dev/null || true
      killed_any=1
    fi
    rm -f "${pidfile}" 2>/dev/null || true
  fi
done

svc="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
if pgrep -af "avahi-publish-service.*${svc}" >/dev/null 2>&1; then
  log "pkill stray avahi-publish-service for ${svc}"
  pkill -f "avahi-publish-service.*${svc}" 2>/dev/null || true
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
