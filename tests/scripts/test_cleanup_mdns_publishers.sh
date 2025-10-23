#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
FALLBACK_DIR="$(mktemp -d)"
trap 'cleanup' EXIT

cleanup() {
  local pid
  for pid in ${BOOT_PID_VALUE:-} ${SERVER_PID_VALUE:-} ${FALLBACK_PID:-}; do
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait ${BOOT_PID_VALUE:-} 2>/dev/null || true
  wait ${SERVER_PID_VALUE:-} 2>/dev/null || true
  wait ${FALLBACK_PID:-} 2>/dev/null || true
  rm -f "${BOOT_PID_FILE:-}" "${SERVER_PID_FILE:-}"
  rm -rf "${TMP_DIR}" "${FALLBACK_DIR}"
}

CLUSTER="testcluster"
ENVIRONMENT="testenv"
SERVICE="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
PID_DIR="/run/sugarkube"
BOOT_PID_FILE="${PID_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-bootstrap.pid"
SERVER_PID_FILE="${PID_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-server.pid"

mkdir -p "${PID_DIR}"

sleep 120 &
BOOT_PID_VALUE=$!
printf '%s\n' "${BOOT_PID_VALUE}" >"${BOOT_PID_FILE}"

sleep 120 &
SERVER_PID_VALUE=$!
printf '%s\n' "${SERVER_PID_VALUE}" >"${SERVER_PID_FILE}"

cat <<'STUB' >"${FALLBACK_DIR}/avahi-publish-service"
#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' TERM INT
while true; do
  sleep 1
done
STUB
chmod +x "${FALLBACK_DIR}/avahi-publish-service"

PATH="${FALLBACK_DIR}:${PATH}" "${FALLBACK_DIR}/avahi-publish-service" "--watch" "${SERVICE}" &
FALLBACK_PID=$!

sleep 1

if [ ! -f "${BOOT_PID_FILE}" ] || [ ! -f "${SERVER_PID_FILE}" ]; then
  echo "PID files were not created" >&2
  exit 1
fi

if ! kill -0 "${BOOT_PID_VALUE}" 2>/dev/null; then
  echo "Bootstrap test process exited early" >&2
  exit 1
fi

if ! kill -0 "${SERVER_PID_VALUE}" 2>/dev/null; then
  echo "Server test process exited early" >&2
  exit 1
fi

OUTPUT=$(SUGARKUBE_CLUSTER="${CLUSTER}" SUGARKUBE_ENV="${ENVIRONMENT}" PATH="${PATH}" bash "${REPO_ROOT}/scripts/cleanup_mdns_publishers.sh")
STATUS=$?

echo "${OUTPUT}" | grep -q "dynamic publishers terminated"

sleep 1

if [ "${STATUS}" -ne 0 ]; then
  echo "cleanup_mdns_publishers.sh failed" >&2
  exit 1
fi

if [ -f "${BOOT_PID_FILE}" ] || [ -f "${SERVER_PID_FILE}" ]; then
  echo "PID files were not removed" >&2
  exit 1
fi

if kill -0 "${BOOT_PID_VALUE}" 2>/dev/null; then
  echo "Bootstrap process still running" >&2
  exit 1
fi

if kill -0 "${SERVER_PID_VALUE}" 2>/dev/null; then
  echo "Server process still running" >&2
  exit 1
fi

if kill -0 "${FALLBACK_PID}" 2>/dev/null; then
  echo "Fallback avahi-publish-service still running" >&2
  exit 1
fi

echo "cleanup_mdns_publishers.sh test passed"
