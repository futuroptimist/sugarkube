#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENV="${SUGARKUBE_ENV:-dev}"
DRY_RUN="${DRY_RUN:-0}"

log() {
  echo "[cleanup-mdns] $*"
}

if [ "${DRY_RUN}" = "1" ]; then
  log "DRY_RUN=1: skipping dynamic publisher cleanup for ${CLUSTER}/${ENV}"
  exit 0
fi

killed_any=0
for phase in bootstrap server; do
  pid_file="/run/sugarkube/mdns-${CLUSTER}-${ENV}-${phase}.pid"
  if [ -f "${pid_file}" ]; then
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
      log "killing ${phase} publisher pid=${pid}"
      kill "${pid}" 2>/dev/null || true
      killed_any=1
    fi
    rm -f "${pid_file}"
  fi
done

svc="_k3s-${CLUSTER}-${ENV}._tcp"
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
