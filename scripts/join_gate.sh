#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

SERVICE_NAME="k3s join lock"
SERVICE_TYPE="_k3s-join-lock._tcp"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
PID_FILE="${SUGARKUBE_JOIN_GATE_PID_FILE:-${RUNTIME_DIR}/join-gate.pid}"
BACKOFF_START="${SUGARKUBE_JOIN_GATE_BACKOFF_START:-1}"
BACKOFF_MAX="${SUGARKUBE_JOIN_GATE_BACKOFF_MAX:-8}"

ensure_runtime_dir() {
  if [ ! -d "${RUNTIME_DIR}" ]; then
    mkdir -p "${RUNTIME_DIR}"
  fi
}

command_required() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    log_info join_gate "action=error" "outcome=missing_command" "command=${name}" >&2
    exit 1
  fi
}

lock_present() {
  if ! command -v avahi-browse >/dev/null 2>&1; then
    return 1
  fi
  if avahi-browse -pt "${SERVICE_TYPE}" 2>/dev/null | grep -q "${SERVICE_TYPE}"; then
    return 0
  fi
  return 1
}

random_port() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import random
random.seed()
print(random.randint(49152, 65535))
PY
    return
  fi
  awk 'BEGIN { srand(); print int(49152 + rand() * (65535 - 49152 + 1)) }'
}

acquire_lock() {
  ensure_runtime_dir
  command_required avahi-publish-service
  wait_for_lock

  if [ -f "${PID_FILE}" ]; then
    local existing
    existing="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [ -n "${existing}" ] && kill -0 "${existing}" 2>/dev/null; then
      log_info join_gate "action=acquire" "outcome=ok" "pid=${existing}" "state=held" >&2
      return 0
    fi
    rm -f "${PID_FILE}"
  fi

  local port
  port="$(random_port)"
  if ! [[ "${port}" =~ ^[0-9]+$ ]]; then
    log_info join_gate "action=acquire" "outcome=error" "reason=port_generation" >&2
    exit 1
  fi

  avahi-publish-service --no-stdin "${SERVICE_NAME}" "${SERVICE_TYPE}" "${port}" >/dev/null 2>&1 &
  local publisher_pid=$!
  sleep 0.1
  if ! kill -0 "${publisher_pid}" 2>/dev/null; then
    log_info join_gate "action=acquire" "outcome=error" "reason=publisher_start" >&2
    exit 1
  fi

  printf '%s\n' "${publisher_pid}" >"${PID_FILE}"
  log_info join_gate "action=acquire" "outcome=ok" "pid=${publisher_pid}" "port=${port}" >&2
}

release_lock() {
  ensure_runtime_dir
  if [ ! -f "${PID_FILE}" ]; then
    log_info join_gate "action=release" "outcome=skip" "reason=pid_missing" >&2
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -z "${pid}" ]; then
    rm -f "${PID_FILE}"
    log_info join_gate "action=release" "outcome=skip" "reason=pid_empty" >&2
    return 0
  fi
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    log_info join_gate "action=release" "outcome=skip" "reason=pid_dead" "pid=${pid}" >&2
    return 0
  fi
  kill "${pid}" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${PID_FILE}"
  log_info join_gate "action=release" "outcome=ok" "pid=${pid}" >&2
}

wait_for_lock() {
  command_required avahi-browse
  if [ -f "${PID_FILE}" ]; then
    local existing
    existing="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [ -n "${existing}" ] && kill -0 "${existing}" 2>/dev/null; then
      log_info join_gate "action=wait" "outcome=held" "pid=${existing}" >&2
      return 0
    fi
  fi

  local backoff="${BACKOFF_START}"
  while lock_present; do
    log_info join_gate "action=wait" "outcome=blocked" "delay=${backoff}" >&2
    sleep "${backoff}"
    if [ "${backoff}" -lt "${BACKOFF_MAX}" ]; then
      backoff=$((backoff * 2))
      if [ "${backoff}" -gt "${BACKOFF_MAX}" ]; then
        backoff="${BACKOFF_MAX}"
      fi
    fi
  done
  log_info join_gate "action=wait" "outcome=ok" >&2
}

usage() {
  cat <<'HELP'
Usage: join_gate.sh <command>

Commands:
  acquire   Acquire the join lock, blocking until it's available.
  release   Release the join lock if held.
  wait      Block until no join lock advertisement is visible.
HELP
}

main() {
  if [ "$#" -eq 0 ]; then
    usage >&2
    exit 2
  fi
  case "$1" in
    acquire)
      acquire_lock
      ;;
    release)
      release_lock
      ;;
    wait)
      wait_for_lock
      ;;
    -h|--help)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
