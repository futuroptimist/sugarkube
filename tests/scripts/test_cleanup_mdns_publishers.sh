#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
helper="${repo_root}/scripts/cleanup_mdns_publishers.sh"

if [ ! -x "${helper}" ]; then
  echo "cleanup helper missing" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
boot_pid=""
server_pid=""
stray_pid=""

cleanup() {
  for pid in "${boot_pid}" "${server_pid}" "${stray_pid}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

runtime_dir="${tmp_dir}/run"
mkdir -p "${runtime_dir}"

sleep 60 &
boot_pid=$!
printf '%s\n' "${boot_pid}" >"${runtime_dir}/mdns-sugar-dev-bootstrap.pid"

sleep 60 &
server_pid=$!
printf '%s\n' "${server_pid}" >"${runtime_dir}/mdns-sugar-dev-server.pid"

bash -c 'exec -a "avahi-publish-service stray _k3s-sugar-dev._tcp" sleep 60' &
stray_pid=$!

log_path="${tmp_dir}/cleanup.log"
SUGARKUBE_RUNTIME_DIR="${runtime_dir}" \
SUGARKUBE_CLUSTER="sugar" \
SUGARKUBE_ENV="dev" \
"${helper}" >"${log_path}" 2>&1

if kill -0 "${boot_pid}" >/dev/null 2>&1; then
  echo "bootstrap publisher still running" >&2
  exit 1
fi

if kill -0 "${server_pid}" >/dev/null 2>&1; then
  echo "server publisher still running" >&2
  exit 1
fi

if kill -0 "${stray_pid}" >/dev/null 2>&1; then
  echo "stray avahi-publish-service process still running" >&2
  exit 1
fi

if [ -e "${runtime_dir}/mdns-sugar-dev-bootstrap.pid" ] || [ -e "${runtime_dir}/mdns-sugar-dev-server.pid" ]; then
  echo "pid files were not removed" >&2
  exit 1
fi

grep -q "dynamic publishers terminated" "${log_path}"
