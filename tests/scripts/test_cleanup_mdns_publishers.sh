#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/cleanup_mdns_publishers.sh"

if [ ! -x "${SCRIPT}" ]; then
  echo "cleanup_mdns_publishers.sh missing or not executable" >&2
  exit 1
fi

TMPDIR="$(mktemp -d)"
runtime_dir="${TMPDIR}/run"
mkdir -p "${runtime_dir}"

boot_pid=""
server_pid=""
stray_pid=""
cleanup() {
  for pid in "${boot_pid}" "${server_pid}" "${stray_pid}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
  rm -rf "${TMPDIR}"
}
trap cleanup EXIT

sleep 30 &
boot_pid=$!
sleep 30 &
server_pid=$!
bash -c "exec -a 'avahi-publish-service _k3s-berry-test._tcp stray' sleep 30" &
stray_pid=$!

printf '%s\n' "${boot_pid}" >"${runtime_dir}/mdns-berry-test-bootstrap.pid"
printf '%s\n' "${server_pid}" >"${runtime_dir}/mdns-berry-test-server.pid"

SUGARKUBE_CLUSTER="berry" \
SUGARKUBE_ENV="test" \
SUGARKUBE_RUNTIME_DIR="${runtime_dir}" \
bash "${SCRIPT}" >"${TMPDIR}/cleanup.log" 2>&1

sleep 0.2

if kill -0 "${boot_pid}" >/dev/null 2>&1; then
  echo "bootstrap publisher process still running" >&2
  exit 1
fi
if kill -0 "${server_pid}" >/dev/null 2>&1; then
  echo "server publisher process still running" >&2
  exit 1
fi
if kill -0 "${stray_pid}" >/dev/null 2>&1; then
  echo "stray publisher process still running" >&2
  exit 1
fi

if [ -f "${runtime_dir}/mdns-berry-test-bootstrap.pid" ]; then
  echo "bootstrap pidfile still present" >&2
  exit 1
fi
if [ -f "${runtime_dir}/mdns-berry-test-server.pid" ]; then
  echo "server pidfile still present" >&2
  exit 1
fi

if ! grep -q "dynamic publishers terminated" "${TMPDIR}/cleanup.log"; then
  echo "expected termination log not found" >&2
  exit 1
fi

echo "cleanup_mdns_publishers script test passed"
