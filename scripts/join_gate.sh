#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

log_join_gate() {
  log_kv info join_gate "$@" >&2
}

log_join_gate_warn() {
  log_kv info join_gate "$@" severity=warn >&2
}

log_join_gate_error() {
  log_kv info join_gate "$@" severity=error >&2
}

SERVICE_TYPE="_k3s-join-lock._tcp"
SERVICE_NAME="${SUGARKUBE_JOIN_GATE_NAME:-k3s join lock}"
if [ -n "${SUGARKUBE_CLUSTER:-}" ]; then
  SERVICE_NAME="${SERVICE_NAME} (${SUGARKUBE_CLUSTER})"
fi
if [ -n "${SUGARKUBE_ENV:-}" ]; then
  SERVICE_NAME="${SERVICE_NAME} (${SUGARKUBE_ENV})"
fi

RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
PID_FILE="${RUNTIME_DIR}/join-gate-avahi.pid"
STATE_FILE="${RUNTIME_DIR}/join-gate-state"

BACKOFF_START_MS="${JOIN_GATE_BACKOFF_START_MS:-500}"
BACKOFF_CAP_MS="${JOIN_GATE_BACKOFF_CAP_MS:-4000}"

ensure_dependencies() {
  local missing=0
  for dep in "$@"; do
    if ! command -v "${dep}" >/dev/null 2>&1; then
      log_join_gate_error action=dependency outcome=error missing="${dep}"
      missing=1
    fi
  done
  if [ "${missing}" -ne 0 ]; then
    exit 1
  fi
}

ensure_runtime_dir() {
  if [ ! -d "${RUNTIME_DIR}" ]; then
    if ! mkdir -p "${RUNTIME_DIR}" 2>/dev/null; then
      log_join_gate_error action=runtime_dir outcome=error path="${RUNTIME_DIR}"
      exit 1
    fi
  fi
}

sleep_ms() {
  local ms="$1"
  if [ "${ms}" -le 0 ]; then
    return 0
  fi
  local seconds
  seconds="$(awk -v value="${ms}" 'BEGIN { printf "%.3f", value / 1000 }')"
  sleep "${seconds}"
}

next_backoff_ms() {
  local current="$1"
  local cap="$2"
  local doubled
  doubled=$((current * 2))
  if [ "${doubled}" -gt "${cap}" ]; then
    printf '%s\n' "${cap}"
  else
    printf '%s\n' "${doubled}"
  fi
}

cleanup_stale_pid() {
  if [ -f "${PID_FILE}" ]; then
    local existing_pid
    existing_pid="$(tr -d '\n' <"${PID_FILE}" 2>/dev/null || true)"
    if [ -n "${existing_pid}" ] && kill -0 "${existing_pid}" 2>/dev/null; then
      log_join_gate action=acquire outcome=ok pid="${existing_pid}" state=already_held
      exit 0
    fi
    rm -f "${PID_FILE}" "${STATE_FILE}" 2>/dev/null || true
  fi
}

has_join_lock() {
  local output
  if ! output="$(avahi-browse -rt "${SERVICE_TYPE}" 2>/dev/null)"; then
    log_join_gate_error action=probe outcome=error command=avahi-browse
    exit 1
  fi
  if printf '%s\n' "${output}" | grep -q "${SERVICE_TYPE}"; then
    return 0
  fi
  return 1
}

wait_for_lock_release() {
  ensure_dependencies avahi-browse
  local attempt=0
  local backoff="${BACKOFF_START_MS}"
  while has_join_lock; do
    log_join_gate action=wait state=locked attempt="${attempt}" backoff_ms="${backoff}"
    sleep_ms "${backoff}"
    backoff="$(next_backoff_ms "${backoff}" "${BACKOFF_CAP_MS}")"
    attempt=$((attempt + 1))
  done
  log_join_gate action=wait outcome=ok attempts="${attempt}"
}

acquire_lock() {
  ensure_dependencies avahi-browse avahi-publish-service
  ensure_runtime_dir
  cleanup_stale_pid

  local backoff="${BACKOFF_START_MS}"
  local attempt=0
  while has_join_lock; do
    log_join_gate action=acquire state=waiting attempt="${attempt}" backoff_ms="${backoff}"
    sleep_ms "${backoff}"
    backoff="$(next_backoff_ms "${backoff}" "${BACKOFF_CAP_MS}")"
    attempt=$((attempt + 1))
  done

  local port
  port=$(( (RANDOM % 16384) + 49152 ))
  local instance
  instance="${SERVICE_NAME} $(hostname -s 2>/dev/null || hostname)"
  instance="${instance## }"
  instance="${instance%% }"

  log_join_gate action=acquire state=publishing attempt="${attempt}" port="${port}"
  avahi-publish-service -s "${instance}" "${SERVICE_TYPE}" "${port}" >/dev/null 2>&1 &
  local pid=$!
  sleep 0.1
  if ! kill -0 "${pid}" 2>/dev/null; then
    wait "${pid}" 2>/dev/null || true
    log_join_gate_error action=acquire outcome=error reason=publisher_failed
    exit 1
  fi

  printf '%s\n' "${pid}" >"${PID_FILE}"
  printf '%s\n' "${instance}" >"${STATE_FILE}"
  log_join_gate action=acquire outcome=ok pid="${pid}" port="${port}"
}

release_lock() {
  ensure_dependencies avahi-publish-service
  ensure_runtime_dir
  if [ ! -f "${PID_FILE}" ]; then
    log_join_gate action=release outcome=skip reason=no_pid_file
    exit 0
  fi
  local pid
  pid="$(tr -d '\n' <"${PID_FILE}" 2>/dev/null || true)"
  if [ -z "${pid}" ]; then
    rm -f "${PID_FILE}" "${STATE_FILE}" 2>/dev/null || true
    log_join_gate_warn action=release outcome=skip reason=empty_pid_file
    exit 0
  fi
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}" "${STATE_FILE}" 2>/dev/null || true
    log_join_gate_warn action=release outcome=skip reason=stale_pid pid="${pid}"
    exit 0
  fi
  if ! kill "${pid}" >/dev/null 2>&1; then
    log_join_gate_error action=release outcome=error pid="${pid}" reason=kill_failed
    exit 1
  fi
  wait "${pid}" 2>/dev/null || true
  rm -f "${PID_FILE}" "${STATE_FILE}" 2>/dev/null || true
  log_join_gate action=release outcome=ok pid="${pid}"
}

usage() {
  cat <<'EOF'
Usage: join_gate.sh <command>

Commands:
  wait     Block until no _k3s-join-lock._tcp records are visible
  acquire  Publish a transient Avahi record to acquire the join gate
  release  Terminate our Avahi publisher if we created one
EOF
}

main() {
  if [ "$#" -lt 1 ]; then
    usage >&2
    exit 2
  fi

  case "$1" in
    wait)
      wait_for_lock_release
      ;;
    acquire)
      acquire_lock
      ;;
    release)
      release_lock
      ;;
    --help|-h)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
