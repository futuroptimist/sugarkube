#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

SERVICE_TYPE="_k3s-join-lock._tcp"
SERVICE_NAME="${SUGARKUBE_JOIN_GATE_NAME:-k3s join gate}" # Avahi display name
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
PID_FILE="${SUGARKUBE_JOIN_GATE_PID_FILE:-${RUNTIME_DIR}/join-gate.pid}"
AVAHI_PUBLISH_BIN="${SUGARKUBE_AVAHI_PUBLISH_BIN:-avahi-publish-service}"
AVAHI_BROWSE_BIN="${SUGARKUBE_AVAHI_BROWSE_BIN:-avahi-browse}"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo 'unknown')"

log_join_gate() {
  log_kv info join_gate "$@" >&2
}

usage() {
  cat <<'USAGE' >&2
Usage: join_gate.sh <command>
Commands:
  acquire   Acquire the join gate lock by publishing an mDNS service
  release   Release the join gate lock if held
  wait      Block until no join gate lock advertisement is visible
USAGE
}

ensure_runtime_dir() {
  if [ ! -d "${RUNTIME_DIR}" ]; then
    mkdir -p "${RUNTIME_DIR}"
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log_join_gate "action=$2" "outcome=error" "reason=${1}_missing"
    exit 1
  fi
}

service_visible() {
  local output
  output="$(${AVAHI_BROWSE_BIN} --parsable --terminate "${SERVICE_TYPE}" 2>/dev/null || true)"
  if [ -n "${output}" ]; then
    return 0
  fi
  return 1
}

generate_lock_id() {
  printf '%04x%04x' "$RANDOM" "$RANDOM"
}

random_port() {
  local base=$((RANDOM % 16384))
  printf '%d' $((base + 49152))
}

acquire_lock() {
  ensure_runtime_dir
  require_command "${AVAHI_BROWSE_BIN}" acquire
  require_command "${AVAHI_PUBLISH_BIN}" acquire

  local attempt=0
  local sleep_secs=1
  while service_visible; do
    attempt=$((attempt + 1))
    log_join_gate "action=acquire" "outcome=blocked" "attempt=${attempt}" "sleep=${sleep_secs}"
    sleep "${sleep_secs}"
    if [ "${sleep_secs}" -lt 8 ]; then
      sleep_secs=$((sleep_secs * 2))
      if [ "${sleep_secs}" -gt 8 ]; then
        sleep_secs=8
      fi
    fi
  done

  local port
  port="$(random_port)"
  local lock_id
  lock_id="$(generate_lock_id)"

  if command -v nohup >/dev/null 2>&1; then
    nohup "${AVAHI_PUBLISH_BIN}" \
      "${SERVICE_NAME} on ${HOSTNAME_SHORT}" \
      "${SERVICE_TYPE}" \
      "${port}" \
      "txt=lock_id=${lock_id}" \
      >/dev/null 2>&1 &
  else
    "${AVAHI_PUBLISH_BIN}" \
      "${SERVICE_NAME} on ${HOSTNAME_SHORT}" \
      "${SERVICE_TYPE}" \
      "${port}" \
      "txt=lock_id=${lock_id}" \
      >/dev/null 2>&1 &
  fi
  local pub_pid=$!
  disown 2>/dev/null || true
  sleep 0.1
  if ! kill -0 "${pub_pid}" 2>/dev/null; then
    log_join_gate "action=acquire" "outcome=error" "reason=publish_failed"
    exit 1
  fi

  printf '%s\n' "${pub_pid}" >"${PID_FILE}"
  log_join_gate "action=acquire" "outcome=ok" "pid=${pub_pid}" "lock_id=${lock_id}" "port=${port}"
  exit 0
}

release_lock() {
  ensure_runtime_dir
  require_command "${AVAHI_PUBLISH_BIN}" release
  if [ ! -f "${PID_FILE}" ]; then
    log_join_gate "action=release" "outcome=skip" "reason=no_pid_file"
    exit 0
  fi

  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -z "${pid}" ]; then
    log_join_gate "action=release" "outcome=skip" "reason=empty_pid"
    rm -f "${PID_FILE}"
    exit 0
  fi

  if [ ! -d "/proc/${pid}" ]; then
    log_join_gate "action=release" "outcome=skip" "reason=not_running" "pid=${pid}"
    rm -f "${PID_FILE}"
    exit 0
  fi

  kill "${pid}" 2>/dev/null || true

  for _ in 1 2 3 4 5; do
    if kill -0 "${pid}" 2>/dev/null; then
      sleep 0.1
    else
      break
    fi
  done

  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
  fi

  rm -f "${PID_FILE}"
  log_join_gate "action=release" "outcome=ok" "pid=${pid}"
  exit 0
}

wait_for_lock() {
  require_command "${AVAHI_BROWSE_BIN}" wait
  local attempt=0
  local sleep_secs=1
  while service_visible; do
    attempt=$((attempt + 1))
    log_join_gate "action=wait" "outcome=blocked" "attempt=${attempt}" "sleep=${sleep_secs}"
    sleep "${sleep_secs}"
    if [ "${sleep_secs}" -lt 8 ]; then
      sleep_secs=$((sleep_secs * 2))
      if [ "${sleep_secs}" -gt 8 ]; then
        sleep_secs=8
      fi
    fi
  done
  log_join_gate "action=wait" "outcome=ok"
  exit 0
}

if [ "$#" -lt 1 ]; then
  usage
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
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
esac
