set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CLEANUP_SCRIPT="${REPO_ROOT}/scripts/cleanup_mdns_publishers.sh"
TMP_DIR="$(mktemp -d)"

cleanup() {
  set +e
  if [ -n "${BOOT_PID:-}" ]; then kill "${BOOT_PID}" 2>/dev/null || true; fi
  if [ -n "${SERVER_PID:-}" ]; then kill "${SERVER_PID}" 2>/dev/null || true; fi
  if [ -n "${FALLBACK_PID:-}" ]; then kill "${FALLBACK_PID}" 2>/dev/null || true; fi
  rm -rf "${TMP_DIR}"
}

trap 'cleanup' EXIT

RUN_DIR="${TMP_DIR}/run"
mkdir -p "${RUN_DIR}"
CLUSTER="sweet"
ENVIRONMENT="test"

sleep 120 &
BOOT_PID=$!
sleep 120 &
SERVER_PID=$!

BOOT_FILE="${RUN_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-bootstrap.pid"
SERVER_FILE="${RUN_DIR}/mdns-${CLUSTER}-${ENVIRONMENT}-server.pid"

echo "${BOOT_PID}" >"${BOOT_FILE}"
echo "${SERVER_PID}" >"${SERVER_FILE}"

(
  export SUGARKUBE_CLUSTER="${CLUSTER}"
  export SUGARKUBE_ENV="${ENVIRONMENT}"
  export SUGARKUBE_RUNTIME_DIR="${RUN_DIR}"
  bash "${CLEANUP_SCRIPT}"
)

if kill -0 "${BOOT_PID}" 2>/dev/null; then
  echo "bootstrap publisher still running" >&2
  exit 1
fi

if kill -0 "${SERVER_PID}" 2>/dev/null; then
  echo "server publisher still running" >&2
  exit 1
fi

if [ -e "${BOOT_FILE}" ] || [ -e "${SERVER_FILE}" ]; then
  echo "pid files not removed after cleanup" >&2
  exit 1
fi

echo 99999 >"${BOOT_FILE}"

FAKE_PUBLISHER="${TMP_DIR}/avahi-publish-service"
cat <<'PUB' >"${FAKE_PUBLISHER}"
#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' TERM INT
sleep 120 &
wait "$!"
PUB
chmod +x "${FAKE_PUBLISHER}"

"${FAKE_PUBLISHER}" "_k3s-${CLUSTER}-${ENVIRONMENT}._tcp" &
FALLBACK_PID=$!
sleep 0.1

(
  export SUGARKUBE_CLUSTER="${CLUSTER}"
  export SUGARKUBE_ENV="${ENVIRONMENT}"
  export SUGARKUBE_RUNTIME_DIR="${RUN_DIR}"
  bash "${CLEANUP_SCRIPT}"
)

if kill -0 "${FALLBACK_PID}" 2>/dev/null; then
  echo "fallback publisher still running" >&2
  exit 1
fi

if [ -e "${BOOT_FILE}" ]; then
  echo "orphan bootstrap pid file not removed" >&2
  exit 1
fi

if [ -e "${SERVER_FILE}" ]; then
  echo "unexpected server pid file present" >&2
  exit 1
fi
