#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"

log() {
  printf '[cleanup-mdns] %s\n' "$*"
}

killed_any=0

if [ -d "${RUNTIME_DIR}" ]; then
  for phase in bootstrap server; do
    pid_file="${RUNTIME_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-${phase}.pid"
    if [ -f "${pid_file}" ]; then
      pid="$(cat "${pid_file}" 2>/dev/null || true)"
      if [ -n "${pid:-}" ] && kill -0 "${pid}" 2>/dev/null; then
        log "killing ${phase} publisher pid=${pid}"
        kill "${pid}" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
          if ! kill -0 "${pid}" 2>/dev/null; then
            break
          fi
          sleep 0.1
        done
        if kill -0 "${pid}" 2>/dev/null; then
          kill -9 "${pid}" 2>/dev/null || true
        fi
        killed_any=1
      fi
      rm -f "${pid_file}" || true
    fi
  done
fi

svc="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
pattern="avahi-publish-service.*${svc}"

if command -v pkill >/dev/null 2>&1; then
  if command -v pgrep >/dev/null 2>&1; then
    if pgrep -af "${pattern}" >/dev/null 2>&1; then
      log "pkill stray avahi-publish-service for ${svc}"
      pkill -f "${pattern}" 2>/dev/null || true
      killed_any=1
    fi
  else
    if pkill -f "${pattern}" 2>/dev/null; then
      log "pkill stray avahi-publish-service for ${svc}"
      killed_any=1
    fi
  fi
fi

if command -v avahi-browse >/dev/null 2>&1; then
  if avahi-browse -pt "${svc}" 2>/dev/null | grep -q "${svc}"; then
    log "WARNING: advert for ${svc} still visible (browser cache may lag)"
  fi
fi

if [ "${killed_any}" -eq 1 ]; then
  log "dynamic publishers terminated"
fi

