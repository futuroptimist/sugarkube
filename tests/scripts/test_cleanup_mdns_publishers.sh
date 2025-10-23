#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="${repo_root}/scripts/cleanup_mdns_publishers.sh"

runtime_base="$(mktemp -d)"
trap 'rc=$?; for pid in "${pids[@]:-}"; do
  if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; fi
 done; rm -rf "${runtime_base}"; exit "$rc"' EXIT

runtime_dir="${runtime_base}/run"
mkdir -p "${runtime_dir}"

declare -a pids=()

sleep 60 &
pids+=($!)
bootstrap_pid=${pids[-1]}
printf '%s\n' "${bootstrap_pid}" >"${runtime_dir}/mdns-sugar-dev-bootstrap.pid"

sleep 60 &
pids+=($!)
server_pid=${pids[-1]}
printf '%s\n' "${server_pid}" >"${runtime_dir}/mdns-sugar-dev-server.pid"

# Launch a stray publisher-style process so the fallback pkill path triggers.
bash -c 'exec -a "avahi-publish-service stray _k3s-sugar-dev._tcp" sleep 60' &
pids+=($!)
stray_pid=${pids[-1]}

output="$(
  SUGARKUBE_CLUSTER=sugar \
  SUGARKUBE_ENV=dev \
  SUGARKUBE_RUNTIME_DIR="${runtime_dir}" \
    bash "${helper}"
)"

printf '%s' "${output}" | grep -q "dynamic publishers terminated"

if [ -f "${runtime_dir}/mdns-sugar-dev-bootstrap.pid" ]; then
  echo "bootstrap pidfile still present" >&2
  exit 1
fi

if [ -f "${runtime_dir}/mdns-sugar-dev-server.pid" ]; then
  echo "server pidfile still present" >&2
  exit 1
fi

if kill -0 "${bootstrap_pid}" 2>/dev/null; then
  echo "bootstrap publisher still running" >&2
  exit 1
fi

if kill -0 "${server_pid}" 2>/dev/null; then
  echo "server publisher still running" >&2
  exit 1
fi

if kill -0 "${stray_pid}" 2>/dev/null; then
  echo "stray publisher still running" >&2
  exit 1
fi

