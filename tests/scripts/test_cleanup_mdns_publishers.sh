#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PID_DIR="/run/sugarkube"
mkdir -p "${PID_DIR}"

CLUSTER="test$(date +%s%N)"
ENV="spec"

BOOT_PID=""
SERVER_PID=""
STRAY_PID=""
DRY_BOOT_PID=""
DRY_SERVER_PID=""

BOOT_FILE=""
SERVER_FILE=""
DRY_BOOT_FILE=""
DRY_SERVER_FILE=""

cleanup() {
  for pid in "${BOOT_PID}" "${SERVER_PID}" "${STRAY_PID}" "${DRY_BOOT_PID}" "${DRY_SERVER_PID}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  rm -f "${BOOT_FILE}" "${SERVER_FILE}" "${DRY_BOOT_FILE}" "${DRY_SERVER_FILE}"
}
trap cleanup EXIT

sleep 60 &
BOOT_PID=$!
sleep 60 &
SERVER_PID=$!
BOOT_FILE="${PID_DIR}/mdns-${CLUSTER}-${ENV}-bootstrap.pid"
SERVER_FILE="${PID_DIR}/mdns-${CLUSTER}-${ENV}-server.pid"
printf '%s\n' "${BOOT_PID}" >"${BOOT_FILE}"
printf '%s\n' "${SERVER_PID}" >"${SERVER_FILE}"

SUGARKUBE_CLUSTER="${CLUSTER}" \
SUGARKUBE_ENV="${ENV}" \
  bash "${REPO_ROOT}/scripts/cleanup_mdns_publishers.sh"

for _ in $(seq 1 10); do
  if ! kill -0 "${BOOT_PID}" 2>/dev/null && ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    break
  fi
  sleep 0.1
done

if kill -0 "${BOOT_PID}" 2>/dev/null; then
  echo "bootstrap publisher still alive" >&2
  exit 1
fi
if kill -0 "${SERVER_PID}" 2>/dev/null; then
  echo "server publisher still alive" >&2
  exit 1
fi
if [ -e "${BOOT_FILE}" ] || [ -e "${SERVER_FILE}" ]; then
  echo "pid files were not removed" >&2
  exit 1
fi

bash -c "exec -a 'avahi-publish-service _k3s-${CLUSTER}-${ENV}._tcp 6443' sleep 60" &
STRAY_PID=$!
sleep 0.2

SUGARKUBE_CLUSTER="${CLUSTER}" \
SUGARKUBE_ENV="${ENV}" \
  bash "${REPO_ROOT}/scripts/cleanup_mdns_publishers.sh"

for _ in $(seq 1 10); do
  if ! kill -0 "${STRAY_PID}" 2>/dev/null; then
    break
  fi
  sleep 0.1
done

if kill -0 "${STRAY_PID}" 2>/dev/null; then
  echo "stray publisher process still running" >&2
  exit 1
fi

DRY_CLUSTER="${CLUSTER}-dry"
sleep 60 &
DRY_BOOT_PID=$!
sleep 60 &
DRY_SERVER_PID=$!
DRY_BOOT_FILE="${PID_DIR}/mdns-${DRY_CLUSTER}-${ENV}-bootstrap.pid"
DRY_SERVER_FILE="${PID_DIR}/mdns-${DRY_CLUSTER}-${ENV}-server.pid"
printf '%s\n' "${DRY_BOOT_PID}" >"${DRY_BOOT_FILE}"
printf '%s\n' "${DRY_SERVER_PID}" >"${DRY_SERVER_FILE}"

DRY_RUN=1 \
SUGARKUBE_CLUSTER="${DRY_CLUSTER}" \
SUGARKUBE_ENV="${ENV}" \
  bash "${REPO_ROOT}/scripts/cleanup_mdns_publishers.sh"

if ! kill -0 "${DRY_BOOT_PID}" 2>/dev/null; then
  echo "dry-run bootstrap publisher was killed" >&2
  exit 1
fi
if ! kill -0 "${DRY_SERVER_PID}" 2>/dev/null; then
  echo "dry-run server publisher was killed" >&2
  exit 1
fi
if [ ! -f "${DRY_BOOT_FILE}" ] || [ ! -f "${DRY_SERVER_FILE}" ]; then
  echo "dry-run pid files were removed" >&2
  exit 1
fi

kill "${DRY_BOOT_PID}" 2>/dev/null || true
kill "${DRY_SERVER_PID}" 2>/dev/null || true
wait "${DRY_BOOT_PID}" >/dev/null 2>&1 || true
wait "${DRY_SERVER_PID}" >/dev/null 2>&1 || true
rm -f "${DRY_BOOT_FILE}" "${DRY_SERVER_FILE}"
DRY_BOOT_PID=""
DRY_SERVER_PID=""

echo "cleanup_mdns_publishers.sh functional test passed"
