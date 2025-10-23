#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"

log() {
  printf '[cleanup-mdns] %s\n' "$*"
}

pid_file_path() {
  local phase="$1"
  printf '%s/mdns-%s-%s-%s.pid' "${RUNTIME_DIR}" "${CLUSTER}" "${ENVIRONMENT}" "${phase}"
}

killed_any=0

for phase in bootstrap server; do
  pid_file="$(pid_file_path "${phase}")"
  if [ ! -f "${pid_file}" ]; then
    continue
  fi
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
    log "killing ${phase} publisher pid=${pid}"
    kill "${pid}" >/dev/null 2>&1 || true
    killed_any=1
  fi
  rm -f "${pid_file}" 2>/dev/null || true
done

svc="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
if command -v pgrep >/dev/null 2>&1 && command -v pkill >/dev/null 2>&1; then
  if pgrep -af "avahi-publish-service.*${svc}" >/dev/null 2>&1; then
    log "pkill stray avahi-publish-service for ${svc}"
    pkill -f "avahi-publish-service.*${svc}" >/dev/null 2>&1 || true
    killed_any=1
  fi
fi

if command -v avahi-browse >/dev/null 2>&1; then
  if avahi-browse -pt "${svc}" 2>/dev/null | grep -q "${svc}"; then
    log "WARNING: advert for ${svc} still visible (browser cache may lag)"
  fi
fi

if [ "${killed_any}" = "1" ]; then
  log "dynamic publishers terminated"
fi
