#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
ENVIRONMENT="${SUGARKUBE_ENV:-dev}"
SERVICE_TYPE="_k3s-join-lock._tcp"
SERVICE_NAME="${SUGARKUBE_JOIN_GATE_NAME:-k3s join lock ${CLUSTER}/${ENVIRONMENT}}"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-/run/sugarkube}"
STATE_FILE="${RUNTIME_DIR}/join-gate-${CLUSTER}-${ENVIRONMENT}.state"

BACKOFF_START="${SUGARKUBE_JOIN_GATE_BACKOFF_START:-1}"
BACKOFF_CAP="${SUGARKUBE_JOIN_GATE_BACKOFF_CAP:-10}"

publisher_pid=""
owner_id=""
HOSTNAME=""
AVAHI_LIVENESS_CONFIRMED=0

log_join_gate() {
  log_info join_gate "$@"
}

log_join_gate_error() {
  log_kv info join_gate "$@"
}

ensure_systemd_unit_active() {
  local unit="$1"
  if [ -z "${unit}" ]; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    log_debug join_gate_systemd outcome=skip reason=systemctl_missing unit="${unit}"
    return 0
  fi
  if systemctl is-active --quiet "${unit}"; then
    log_debug join_gate_systemd outcome=ok state=active unit="${unit}"
    return 0
  fi

  local start_cmd
  if [ "${EUID}" -eq 0 ]; then
    start_cmd=(systemctl start "${unit}")
  elif command -v sudo >/dev/null 2>&1; then
    start_cmd=(sudo systemctl start "${unit}")
  else
    log_info join_gate_systemd outcome=skip reason=sudo_missing unit="${unit}" severity=warn
    return 1
  fi

  if "${start_cmd[@]}" >/dev/null 2>&1; then
    log_info join_gate_systemd outcome=started unit="${unit}" severity=info
    return 0
  fi

  local rc=$?
  log_info join_gate_systemd outcome=error unit="${unit}" status="${rc}" severity=warn
  return "${rc}"
}

ensure_avahi_systemd_units() {
  ensure_systemd_unit_active dbus || true
  ensure_systemd_unit_active avahi-daemon || true
}

ensure_tools() {
  local missing=0
  local tool
  for tool in avahi-browse avahi-publish-service; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
      log_join_gate_error action=check outcome=error missing="${tool}"
      missing=1
    fi
  done
  if [ "${missing}" -ne 0 ]; then
    exit 1
  fi
}

ensure_runtime_dir() {
  if mkdir -p "${RUNTIME_DIR}" 2>/dev/null; then
    return 0
  fi
  log_join_gate_error action=runtime_dir outcome=error path="${RUNTIME_DIR}"
  exit 1
}

wait_for_avahi_bus() {
  ensure_avahi_systemd_units || true
  if ! command -v gdbus >/dev/null 2>&1; then
    return 0
  fi
  # Capture exit status before using it in conditionals
  # Temporarily disable set -e to capture non-zero exit status
  local status
  set +e
  "${SCRIPT_DIR}/wait_for_avahi_dbus.sh"
  status=$?
  set -e
  if [ "${status}" -eq 0 ]; then
    return 0
  fi
  # Exit status 2 means D-Bus unavailable but CLI tools work (soft failure/skip)
  # This is a valid success condition - the join can proceed
  if [ "${status}" -eq 2 ]; then
    log_join_gate action=dbus_wait outcome=skip status="${status}"
    return 0
  fi
  log_join_gate_error action=dbus_wait outcome=error status="${status}"
  return 1
}

ensure_avahi_liveness_signal() {
  if [ "${AVAHI_LIVENESS_CONFIRMED}" -eq 1 ]; then
    return 0
  fi

  local wait_status=0
  if command -v gdbus >/dev/null 2>&1; then
    if "${SCRIPT_DIR}/wait_for_avahi_dbus.sh"; then
      log_join_gate action=avahi_dbus outcome=ready
    else
      wait_status=$?
      if [ "${wait_status}" -eq 2 ]; then
        log_join_gate action=avahi_dbus outcome=disabled
      else
        log_join_gate_error action=avahi_dbus outcome=error status="${wait_status}"
      fi
    fi
  else
    log_join_gate action=avahi_dbus outcome=skip reason=gdbus_missing
  fi

  # Build specific service type to check for k3s cluster services
  # This is more reliable than --all which may return no results on fresh networks
  local service_type="_k3s-${CLUSTER}-${ENVIRONMENT}._tcp"
  
  local attempt
  local status
  local browse_output
  local lines
  for attempt in 1 2; do
    status=0
    browse_output=""
    # Use specific service type with 5-second timeout (matches mdns_ready.sh behavior)
    # The -r (--resolve) flag is needed to get actual service records, not just announcements
    # timeout command ensures we don't hang if avahi-browse doesn't terminate
    if command -v timeout >/dev/null 2>&1; then
      if ! browse_output="$(timeout 5 avahi-browse -rt "${service_type}" --parsable 2>/dev/null)"; then
        status=$?
        browse_output=""
      fi
    else
      # Fallback without timeout command (less reliable but still functional)
      if ! browse_output="$(avahi-browse -rt "${service_type}" --parsable --timeout=5 2>/dev/null)"; then
        status=$?
        browse_output=""
      fi
    fi
    lines="$(printf '%s\n' "${browse_output}" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [ "${status}" -eq 0 ] && [ -n "${lines}" ] && [ "${lines}" -gt 0 ]; then
      log_join_gate action=avahi_liveness outcome=ok attempt="${attempt}" lines="${lines}" service_type="${service_type}"
      AVAHI_LIVENESS_CONFIRMED=1
      return 0
    fi
    log_join_gate action=avahi_liveness outcome=retry attempt="${attempt}" status="${status}" lines="${lines:-0}" service_type="${service_type}"
    if [ "${attempt}" -eq 1 ]; then
      sleep 1
    fi
  done

  log_join_gate_error action=avahi_liveness outcome=error reason=no_results service_type="${service_type}"
  return 1
}

read_state_file() {
  local key value
  JOIN_STATE_PID=""
  JOIN_STATE_HOST=""
  JOIN_STATE_OWNER=""
  JOIN_STATE_PORT=""
  if [ ! -f "${STATE_FILE}" ]; then
    return 1
  fi
  while IFS='=' read -r key value; do
    case "${key}" in
      pid) JOIN_STATE_PID="${value}" ;;
      host) JOIN_STATE_HOST="${value}" ;;
      owner) JOIN_STATE_OWNER="${value}" ;;
      port) JOIN_STATE_PORT="${value}" ;;
    esac
  done <"${STATE_FILE}"
  return 0
}

cleanup_stale_state() {
  if ! read_state_file; then
    return 0
  fi
  if [ -n "${JOIN_STATE_PID}" ] && kill -0 "${JOIN_STATE_PID}" >/dev/null 2>&1; then
    return 0
  fi
  rm -f "${STATE_FILE}" || true
}
random_port() {
  if command -v shuf >/dev/null 2>&1; then
    shuf -i 49152-65535 -n 1
    return 0
  fi
  python3 - <<'PY'
import random
print(random.randint(49152, 65535))
PY
}

random_owner_id() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen
    return 0
  fi
  python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
}

lock_present() {
  local output
  local status=0
  output="$(avahi-browse --terminate --parsable "${SERVICE_TYPE}" 2>/dev/null)" || status=$?
  if [ "${status}" -eq 255 ]; then
    log_join_gate_error action=probe outcome=error status="${status}" reason=avahi_unavailable
    return 2
  fi
  if [ "${status}" -ne 0 ] && [ "${status}" -ne 1 ]; then
    log_join_gate_error action=probe outcome=error status="${status}"
    return 2
  fi
  if printf '%s\n' "${output}" | grep -Fq ";${SERVICE_TYPE};"; then
    return 0
  fi
  return 1
}

wait_for_clear() {
  local attempt=0
  local delay
  delay="${BACKOFF_START}"
  if [ -z "${delay}" ]; then
    delay=1
  fi
  local cap="${BACKOFF_CAP}"
  if [ -z "${cap}" ]; then
    cap=10
  fi
  while :; do
    local present_status
    if lock_present; then
      present_status=0
    else
      present_status=$?
    fi
    if [ "${present_status}" -eq 0 ]; then
      attempt=$((attempt + 1))
      log_join_gate action=wait outcome=busy attempt="${attempt}" delay="${delay}"
      sleep "${delay}"
      if [ "${delay}" -lt "${cap}" ]; then
        delay=$((delay * 2))
        if [ "${delay}" -gt "${cap}" ]; then
          delay="${cap}"
        fi
      fi
      continue
    fi
    case "${present_status}" in
      0)
        ;;
      1)
        log_join_gate action=wait outcome=clear attempts="${attempt}"
        return 0
        ;;
      2)
        log_join_gate_error action=wait outcome=error
        return 1
        ;;
    esac
  done
}

write_state() {
  umask 077
  printf 'pid=%s\nhost=%s\nowner=%s\nport=%s\n' \
    "${publisher_pid}" "${HOSTNAME}" "${owner_id}" "${publish_port}" >"${STATE_FILE}"
}

start_publisher() {
  publish_port="$(random_port)"
  if [ -z "${publish_port}" ]; then
    log_join_gate_error action=acquire outcome=error reason=no_port
    return 1
  fi
  owner_id="$(random_owner_id)"
  if [ -z "${owner_id}" ]; then
    log_join_gate_error action=acquire outcome=error reason=no_owner_id
    return 1
  fi
  local host_label
  host_label="${HOSTNAME}"
  avahi-publish-service -s "${SERVICE_NAME}" "${SERVICE_TYPE}" "${publish_port}" "host=${host_label}" "owner=${owner_id}" >/dev/null 2>&1 &
  publisher_pid=$!
  sleep 0.2
  if ! kill -0 "${publisher_pid}" >/dev/null 2>&1; then
    local status=0
    wait "${publisher_pid}" >/dev/null 2>&1 || status=$?
    log_join_gate_error action=acquire outcome=error reason=publisher_exit status="${status}"
    publisher_pid=""
    return 1
  fi
  if ! write_state; then
    log_join_gate_error action=acquire outcome=error reason=state_write
    kill "${publisher_pid}" >/dev/null 2>&1 || true
    wait "${publisher_pid}" >/dev/null 2>&1 || true
    publisher_pid=""
    return 1
  fi
  log_join_gate action=acquire outcome=ok pid="${publisher_pid}" port="${publish_port}" owner="${owner_id}"
  return 0
}

acquire_lock() {
  ensure_tools
  ensure_runtime_dir
  wait_for_avahi_bus || return 1
  ensure_avahi_liveness_signal || return 1
  cleanup_stale_state
  HOSTNAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"
  if read_state_file && [ "${JOIN_STATE_HOST}" = "${HOSTNAME}" ] && [ -n "${JOIN_STATE_PID}" ] && kill -0 "${JOIN_STATE_PID}" >/dev/null 2>&1; then
    log_join_gate action=acquire outcome=ok pid="${JOIN_STATE_PID}" owner="${JOIN_STATE_OWNER:-existing}" port="${JOIN_STATE_PORT:-unknown}" mode=existing
    return 0
  fi
  wait_for_clear || return 1
  if ! start_publisher; then
    rm -f "${STATE_FILE}" || true
    return 1
  fi
}

release_lock() {
  ensure_runtime_dir
  HOSTNAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"
  if ! read_state_file; then
    log_join_gate action=release outcome=skip reason=no_state
    return 0
  fi
  if [ -z "${JOIN_STATE_PID}" ]; then
    rm -f "${STATE_FILE}" || true
    log_join_gate action=release outcome=skip reason=no_pid
    return 0
  fi
  if [ "${JOIN_STATE_HOST}" != "${HOSTNAME}" ]; then
    log_join_gate action=release outcome=skip reason=foreign owner_host="${JOIN_STATE_HOST}" pid="${JOIN_STATE_PID}"
    return 0
  fi
  if ! kill "${JOIN_STATE_PID}" >/dev/null 2>&1; then
    if kill -0 "${JOIN_STATE_PID}" >/dev/null 2>&1; then
      log_join_gate_error action=release outcome=error reason=signal_failed pid="${JOIN_STATE_PID}"
      return 1
    fi
  fi
  local waited=0
  while kill -0 "${JOIN_STATE_PID}" >/dev/null 2>&1; do
    if [ -r "/proc/${JOIN_STATE_PID}/stat" ]; then
      local proc_state
      proc_state="$(awk '{print $3}' "/proc/${JOIN_STATE_PID}/stat" 2>/dev/null || echo "")"
      if [ "${proc_state}" = "Z" ] || [ "${proc_state}" = "z" ]; then
        break
      fi
    else
      break
    fi
    sleep 0.1
    waited=$((waited + 1))
    if [ "${waited}" -eq 30 ]; then
      log_join_gate action=release outcome=pending reason=term_timeout pid="${JOIN_STATE_PID}"
      kill -KILL "${JOIN_STATE_PID}" >/dev/null 2>&1 || true
    fi
    if [ "${waited}" -ge 50 ]; then
      if kill -0 "${JOIN_STATE_PID}" >/dev/null 2>&1; then
        log_join_gate_error action=release outcome=error reason=still_running pid="${JOIN_STATE_PID}"
        return 1
      fi
    fi
  done
  rm -f "${STATE_FILE}" || true
  log_join_gate action=release outcome=ok pid="${JOIN_STATE_PID}" owner="${JOIN_STATE_OWNER:-unknown}" port="${JOIN_STATE_PORT:-unknown}"
}

wait_lock() {
  ensure_tools
  ensure_runtime_dir
  wait_for_avahi_bus || return 1
  ensure_avahi_liveness_signal || return 1
  cleanup_stale_state
  HOSTNAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"
  if read_state_file && [ "${JOIN_STATE_HOST}" = "${HOSTNAME}" ] && [ -n "${JOIN_STATE_PID}" ] && kill -0 "${JOIN_STATE_PID}" >/dev/null 2>&1; then
    log_join_gate action=wait outcome=clear attempts=0 mode=existing
    return 0
  fi
  wait_for_clear
}

usage() {
  cat <<'EOF'
Usage: join_gate.sh <acquire|release|wait>
EOF
}

main() {
  if [ "$#" -lt 1 ]; then
    usage >&2
    exit 2
  fi
  local cmd="$1"
  shift || true
  case "${cmd}" in
    acquire)
      acquire_lock
      ;;
    release)
      release_lock
      ;;
    wait)
      wait_lock
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
