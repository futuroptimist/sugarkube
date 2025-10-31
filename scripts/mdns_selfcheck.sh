#!/usr/bin/env bash
# shellcheck disable=SC3040,SC3041,SC3043
set -eu

if (set -o pipefail) 2>/dev/null; then
  set -o pipefail
fi

if (set -E) 2>/dev/null; then
  set -E
fi

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

SERVICE_CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
SERVICE_ENV="${SUGARKUBE_ENV:-dev}"
EXPECTED_HOST="${SUGARKUBE_EXPECTED_HOST:-}"
EXPECTED_IPV4="${SUGARKUBE_EXPECTED_IPV4:-}"
EXPECTED_ROLE="${SUGARKUBE_EXPECTED_ROLE:-}"
EXPECTED_PHASE="${SUGARKUBE_EXPECTED_PHASE:-}"
ATTEMPTS="${SUGARKUBE_SELFCHK_ATTEMPTS:-12}"
BACKOFF_START_MS="${SUGARKUBE_SELFCHK_BACKOFF_START_MS:-500}"
BACKOFF_CAP_MS="${SUGARKUBE_SELFCHK_BACKOFF_CAP_MS:-5000}"
JITTER_FRACTION="${JITTER:-0.2}"
EXPECTED_PORT="${SUGARKUBE_EXPECTED_PORT:-6443}"

case "${EXPECTED_PORT}" in
  ''|*[!0-9]*) EXPECTED_PORT=6443 ;;
esac

if command -v tcpdump >/dev/null 2>&1; then
  TCPDUMP_AVAILABLE=1
else
  TCPDUMP_AVAILABLE=0
fi
if [ -z "${SUGARKUBE_MDNS_WIRE_PROOF:-}" ]; then
  if [ "${TCPDUMP_AVAILABLE}" -eq 1 ]; then
    SUGARKUBE_MDNS_WIRE_PROOF=1
  else
    SUGARKUBE_MDNS_WIRE_PROOF=0
  fi
fi
export SUGARKUBE_MDNS_WIRE_PROOF

if command -v curl >/dev/null 2>&1; then
  CURL_BIN="$(command -v curl)"
else
  CURL_BIN=""
fi
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="$(command -v timeout)"
else
  TIMEOUT_BIN=""
fi
if command -v bash >/dev/null 2>&1; then
  BASH_BIN="$(command -v bash)"
else
  BASH_BIN=""
fi
MDNS_SOCKET_CHECK_STATUS="skipped"
MDNS_SOCKET_CHECK_METHOD=""

script_start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

elapsed_since_start_ms() {
  python3 - "$@" <<'PY'
import sys
import time

try:
    start = int(sys.argv[1])
except (IndexError, ValueError):
    start = 0
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
}

now_ms() {
  python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

kv_escape() {
  printf '%s' "${1}" | tr '\n' ' ' | sed 's/"/\\"/g'
}

join_args_for_log() {
  if [ "$#" -eq 0 ]; then
    printf '%s' ""
    return 0
  fi
  python3 - "$@" <<'PY'
import shlex
import sys
print(' '.join(shlex.quote(arg) for arg in sys.argv[1:]))
PY
}

MDNS_LAST_CMD_DISPLAY=""
MDNS_LAST_CMD_DURATION_MS=""
MDNS_LAST_CMD_OUTPUT=""
MDNS_LAST_CMD_RC=""
MDNS_LAST_CMD_PARSED_IPV4=""
MDNS_LAST_FAILURE_COMMAND=""
MDNS_LAST_FAILURE_DURATION=""

run_command_capture() {
  if [ "$#" -lt 2 ]; then
    return 127
  fi
  local label="$1"
  shift
  local cmd_display
  cmd_display="$(join_args_for_log "$@" 2>/dev/null || printf '%s' "$*")"
  local start_ms
  start_ms="$(now_ms)"
  local output
  local rc
  if ! output="$("$@" 2>&1)"; then
    rc=$?
  else
    rc=0
  fi
  local duration_ms
  duration_ms="$(elapsed_since_start_ms "${start_ms}" 2>/dev/null || printf '%s' 0)"
  case "${duration_ms}" in
    ''|*[!0-9]*) duration_ms=0 ;;
  esac
  MDNS_LAST_CMD_DISPLAY="${cmd_display}"
  MDNS_LAST_CMD_DURATION_MS="${duration_ms}"
  # shellcheck disable=SC2034  # stored for external consumers of the sourcing shell
  MDNS_LAST_CMD_OUTPUT="${output}"
  MDNS_LAST_CMD_RC="${rc}"
  MDNS_LAST_CMD_PARSED_IPV4=""
  local outcome
  if [ "${rc}" -eq 0 ]; then
    outcome="ok"
  else
    outcome="fail"
  fi
  local command_kv
  command_kv="command=\"$(kv_escape "${cmd_display}")\""
  local output_kv
  output_kv="output=\"$(kv_escape "${output}")\""
  log_debug mdns_command label="${label}" outcome="${outcome}" rc="${rc}" duration_ms="${duration_ms}" "${command_kv}" "${output_kv}"
  printf '%s' "${output}"
  return "${rc}"
}

SELF_RESOLVE_STATUS=3
SELF_RESOLVE_HOST=""
SELF_RESOLVE_IPV4=""
SELF_RESOLVE_COMMAND=""
SELF_RESOLVE_DURATION=""
SELF_RESOLVE_REASON=""

MDNS_RESOLUTION_STATUS_LOGGED=0
MDNS_RESOLUTION_STATUS_NSS=0
MDNS_RESOLUTION_STATUS_RESOLVE=0
MDNS_RESOLUTION_STATUS_BROWSE=0

extract_wait_field() {
  local field_name="$1"
  if [ -z "${field_name}" ]; then
    return 1
  fi
  # Parse the first key=value pair matching the requested field from the
  # structured log output emitted by wait_for_avahi_dbus.sh.
  awk -v key="${field_name}" '
    {
      for (i = 1; i <= NF; i++) {
        if (index($i, key "=") == 1) {
          value = substr($i, length(key) + 2)
          gsub(/^[[:space:]]+/, "", value)
          gsub(/[[:space:]]+$/, "", value)
          gsub(/"/, "", value)
          print value
          exit
        }
      }
    }
  ' 2>/dev/null
}

mdns_resolution_status_emit() {
  local outcome="$1"
  shift || true
  [ -n "${outcome}" ] || outcome="unknown"
  if [ "${MDNS_RESOLUTION_STATUS_LOGGED}" = "1" ]; then
    return 0
  fi
  log_info \
    mdns_resolution_status \
    outcome="${outcome}" \
    nss_ok="${MDNS_RESOLUTION_STATUS_NSS}" \
    resolve_ok="${MDNS_RESOLUTION_STATUS_RESOLVE}" \
    browse_ok="${MDNS_RESOLUTION_STATUS_BROWSE}" \
    "$@"
  MDNS_RESOLUTION_STATUS_LOGGED=1
}

mdns_check_nss_host() {
  local host="$1"
  local expected_ipv4="$2"

  if [ -z "${host}" ]; then
    return 1
  fi
  if ! command -v getent >/dev/null 2>&1; then
    return 1
  fi

  local resolved=""
  resolved="$(getent hosts "${host}" 2>/dev/null | awk 'NR==1 {print $1}' | head -n1)"
  if [ -z "${resolved}" ]; then
    return 1
  fi

  if [ -n "${expected_ipv4}" ] && [ "${resolved}" != "${expected_ipv4}" ]; then
    return 2
  fi

  printf '%s' "${resolved}"
  return 0
}

case "${ATTEMPTS}" in
  ''|*[!0-9]*) ATTEMPTS=1 ;;
  0) ATTEMPTS=1 ;;
esac
case "${BACKOFF_START_MS}" in
  ''|*[!0-9]*) BACKOFF_START_MS=500 ;;
esac
case "${BACKOFF_CAP_MS}" in
  ''|*[!0-9]*) BACKOFF_CAP_MS=5000 ;;
esac

if [ -z "${EXPECTED_HOST}" ]; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck_failure outcome=miss reason=missing_expected_host attempt=0 ms_elapsed="${elapsed_ms}"
  exit 2
fi

AVAHI_WAIT_ATTEMPTED=0

dbus_mode="${SUGARKUBE_MDNS_DBUS:-auto}"
if [ "${dbus_mode}" != "0" ]; then
  dbus_script="${SCRIPT_DIR}/mdns_selfcheck_dbus.sh"
  if [ -x "${dbus_script}" ]; then
    AVAHI_WAIT_ATTEMPTED=1
    if SUGARKUBE_MDNS_DBUS=1 "${dbus_script}"; then
      exit 0
    fi
    status=$?
    case "${status}" in
      # 0=ok, 1=transient fail, 2=unsupported -> CLI fallback
      1)
        log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_first_attempt_failed fallback=cli
        ;;
      2)
        AVAHI_WAIT_ATTEMPTED=0
        log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_unsupported fallback=cli
        ;;
      0)
        ;;
      *)
        exit "${status}"
        ;;
    esac
  else
    log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_script_missing fallback=cli
  fi
else
  log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_disabled fallback=cli
fi

if [ "${AVAHI_WAIT_ATTEMPTED}" -eq 0 ] && [ "${dbus_mode}" != "0" ]; then
  avahi_wait_output=""
  if ! avahi_wait_output="$("${SCRIPT_DIR}/wait_for_avahi_dbus.sh" 2>&1)"; then
    status=$?
    if [ -n "${avahi_wait_output}" ]; then
      printf '%s\n' "${avahi_wait_output}"
    fi
    case "${status}" in
      2)
        log_debug mdns_selfcheck_dbus outcome=skip reason=avahi_dbus_wait_skipped fallback=cli
        ;;
      1)
        wait_reason="$(printf '%s\n' "${avahi_wait_output}" | extract_wait_field reason || true)"
        wait_systemd_detail="$(printf '%s\n' "${avahi_wait_output}" | extract_wait_field systemd_detail || true)"
        wait_bus_error="$(printf '%s\n' "${avahi_wait_output}" | extract_wait_field bus_error || true)"
        wait_bus_status="$(printf '%s\n' "${avahi_wait_output}" | extract_wait_field bus_status || true)"
        if [ "${wait_reason}" = "systemd_unavailable" ] ||
          { [ -n "${wait_systemd_detail}" ] && printf '%s\n' "${wait_systemd_detail}" | grep -Ei \
            'System_has_not_been_booted_with_systemd|Systemd_service_manager_is_not_running|Failed_to_connect_to_bus|Failed_to_get_D-Bus_connection|No_such_file_or_directory' >/dev/null; } ||
          { [ -n "${wait_bus_error}" ] && printf '%s\n' "${wait_bus_error}" | grep -Ei \
            'No_such_file_or_directory|Failed_to_connect_to_socket|Connection_refused|System_has_not_been_booted_with_systemd|Systemd_service_manager_is_not_running' >/dev/null; } ||
          [ "${wait_bus_status}" = "systemd_wait" ]; then
          log_debug mdns_selfcheck_dbus outcome=skip reason=avahi_dbus_wait_systemd_unavailable fallback=cli
        else
          elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
          log_info mdns_selfcheck_failure outcome=miss reason=avahi_dbus_wait_failed attempt=0 ms_elapsed="${elapsed_ms}"
          exit "${status}"
        fi
        ;;
      *)
        elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
        log_info mdns_selfcheck_failure outcome=miss reason=avahi_dbus_wait_failed attempt=0 ms_elapsed="${elapsed_ms}"
        exit "${status}"
        ;;
    esac
  elif [ -n "${avahi_wait_output}" ]; then
    printf '%s\n' "${avahi_wait_output}"
  fi
fi

if ! command -v avahi-browse >/dev/null 2>&1; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck_failure outcome=miss reason=avahi_browse_missing attempt=0 ms_elapsed="${elapsed_ms}"
  exit 3
fi
if ! command -v avahi-resolve >/dev/null 2>&1; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck_failure outcome=miss reason=avahi_resolve_missing attempt=0 ms_elapsed="${elapsed_ms}"
  exit 3
fi

SERVICE_TYPE="_k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}._tcp"

# Accept both short host and FQDN in browse results
EXPECTED_SHORT_HOST="${EXPECTED_HOST%.local}"

ACTIVE_QUERY_RAW="${MDNS_ACTIVE_QUERY_SECS:-}"
if [ -z "${ACTIVE_QUERY_RAW}" ]; then
  ACTIVE_QUERY_RAW="${MDDNS_ACTIVE_QUERY_SECS:-5}"
fi
ACTIVE_QUERY_WINDOW_MS="$({
  python3 - <<'PY' "${ACTIVE_QUERY_RAW}"
import sys

def parse_secs(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    if value < 0:
        value = 0.0
    return int(value * 1000)

arg = sys.argv[1] if len(sys.argv) > 1 else ""
print(parse_secs(arg))
PY
} 2>/dev/null)"
case "${ACTIVE_QUERY_WINDOW_MS}" in
  ''|*[!0-9]*) ACTIVE_QUERY_WINDOW_MS=0 ;;
esac
if [ "${ACTIVE_QUERY_WINDOW_MS}" -gt 0 ]; then
  ACTIVE_QUERY_ENABLED=1
else
  ACTIVE_QUERY_WINDOW_MS=0
  ACTIVE_QUERY_ENABLED=0
fi

INITIAL_BROWSE_OUTPUT=""
INITIAL_BROWSE_READY=0

SELF_HOSTNAME_SOURCE=""
if [ "${HOSTNAME+set}" = "set" ] && [ -n "${HOSTNAME}" ]; then
  SELF_HOSTNAME_SOURCE="${HOSTNAME}"
fi
if [ -z "${SELF_HOSTNAME_SOURCE}" ]; then
  SELF_HOSTNAME_SOURCE="$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
fi
if [ -z "${SELF_HOSTNAME_SOURCE}" ]; then
  SELF_HOSTNAME_SOURCE="${EXPECTED_HOST}"
fi

SELF_HOSTNAME_ALIASES="$({
  python3 - <<'PY' "${SELF_HOSTNAME_SOURCE}" "${EXPECTED_HOST}"
import sys

aliases = []
seen = set()

def push(value):
    value = (value or "").strip().lower().rstrip('.')
    if not value:
        return
    if value in seen:
        return
    seen.add(value)
    aliases.append(value)

def expand(raw):
    if not raw:
        return
    push(raw)
    if raw.endswith('.local'):
        base = raw[:-6]
        push(base)
    else:
        push(raw + '.local')

for arg in sys.argv[1:]:
    expand((arg or '').strip().lower())

print('\n'.join(aliases))
PY
} 2>/dev/null)"
if [ -n "${SELF_HOSTNAME_ALIASES}" ]; then
  HOSTNAME_CHECK_ENABLED=1
else
  HOSTNAME_CHECK_ENABLED=0
fi

SELF_LOCAL_HOST=""
if [ -n "${SELF_HOSTNAME_ALIASES}" ]; then
  local_self_aliases="${SELF_HOSTNAME_ALIASES}"
  old_ifs="${IFS}"
  IFS="$(printf '\n')"
  for self_alias in ${local_self_aliases}; do
    case "${self_alias}" in
      *.local)
        SELF_LOCAL_HOST="${self_alias}"
        break
        ;;
    esac
  done
  IFS="${old_ifs}"
fi
if [ -z "${SELF_LOCAL_HOST}" ]; then
  raw_self_host="$(hostname 2>/dev/null || true)"
  raw_self_host="$(printf '%s' "${raw_self_host}" | tr '[:upper:]' '[:lower:]')"
  raw_self_host="${raw_self_host%.}"
  if [ -n "${raw_self_host}" ]; then
    case "${raw_self_host}" in
      *.local)
        SELF_LOCAL_HOST="${raw_self_host}"
        ;;
      *)
        SELF_LOCAL_HOST="${raw_self_host}.local"
        ;;
    esac
  fi
fi

host_matches_self() {
  candidate="$1"
  if [ -z "${candidate}" ]; then
    return 1
  fi
  local lowered
  lowered="$(printf '%s' "${candidate}" | tr '[:upper:]' '[:lower:]')"
  lowered="${lowered%.}"
  if [ -z "${lowered}" ]; then
    return 1
  fi
  if [ "${HOSTNAME_CHECK_ENABLED}" -ne 1 ]; then
    return 1
  fi
  local alias
  local old_ifs="${IFS}"
  IFS="$(printf '\n')"
  for alias in ${SELF_HOSTNAME_ALIASES}; do
    if [ "${lowered}" = "${alias}" ]; then
      IFS="${old_ifs}"
      return 0
    fi
  done
  IFS="${old_ifs}"
  return 1
}

parse_browse() {
  awk -v svc="${SERVICE_TYPE}" \
      -v expected_host="${EXPECTED_HOST}" \
      -v short_host="${EXPECTED_SHORT_HOST}" \
      -v expected_role="${EXPECTED_ROLE}" \
      -v expected_phase="${EXPECTED_PHASE}" \
      -v cluster="${SERVICE_CLUSTER}" \
      -v env="${SERVICE_ENV}" \
      -v sq="'" '
    function dequote(value,    first, last) {
      if (length(value) < 2) {
        return value
      }
      first = substr(value, 1, 1)
      last = substr(value, length(value), 1)
      if ((first == "\"" && last == "\"") || (first == "\047" && last == "\047")) {
        return substr(value, 2, length(value) - 2)
      }
      return value
    }

    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }

    function strip_and_trim(value) {
      value = dequote(value)
      gsub(/\\"/, "\"", value)
      gsub(/\\\047/, sq, value)
      gsub(/\\\\/, "\\", value)
      value = dequote(value)
      return trim(value)
    }

    BEGIN { FS = ";" }
    $1 == "=" {
      delete fields
      for (i = 1; i <= NF; i++) {
        fields[i] = strip_and_trim($i)
      }

      type_idx = -1
      for (i = 1; i <= NF; i++) {
        if (fields[i] == svc) { type_idx = i; break }
      }
      if (type_idx < 0) next

      inst_idx = type_idx - 1
      host_idx = type_idx + 2
      port_idx = type_idx + 4
      if (inst_idx < 1 || host_idx > NF || port_idx > NF) next

      instance = fields[inst_idx]
      host = fields[host_idx]
      port = fields[port_idx]

      if (host == "") next

      host_match = 0
      if (expected_host != "" && host == expected_host) host_match = 1
      if (!host_match && short_host != "") {
        if (host == short_host) host_match = 1
        else if (host == short_host ".local") host_match = 1
      }
      if (!host_match && expected_host ~ /\.local$/) {
        base_host = substr(expected_host, 1, length(expected_host) - 6)
        if (host == base_host) host_match = 1
      }
      if (!host_match) next

      delete txt
      for (j = port_idx + 1; j <= NF; j++) {
        piece = fields[j]
        if (piece == "") continue
        if (tolower(substr(piece, 1, 4)) != "txt=") continue

        entry = strip_and_trim(substr(piece, 5))
        if (entry == "") continue

        eq_pos = index(entry, "=")
        if (eq_pos <= 0) continue

        key = trim(substr(entry, 1, eq_pos - 1))
        value = strip_and_trim(substr(entry, eq_pos + 1))
        if (key == "") continue
        txt[key] = value
      }

      if (cluster != "" && ( !("cluster" in txt) || txt["cluster"] != cluster)) next
      if (env != "" && ( !("env" in txt) || txt["env"] != env)) next
      if (expected_role != "" && ( !("role" in txt) || txt["role"] != expected_role)) next
      if (expected_phase != "" && ( !("phase" in txt) || txt["phase"] != expected_phase)) next

      print instance "|" host "|" port
      exit 0
    }
  '
}

resolve_host() {
  local host="$1"
  if [ -z "${host}" ]; then
    return 1
  fi

  local output
  if ! output="$(run_command_capture avahi_resolve avahi-resolve -n "${host}")"; then
    return 1
  fi

  local any_addr=""
  local ipv4_addr=""
  local line field
  while IFS= read -r line; do
    [ -n "${line}" ] || continue
    # shellcheck disable=SC2086
    set -- ${line}
    shift
    for field in "$@"; do
      if [ -z "${any_addr}" ]; then
        any_addr="${field}"
      fi
      case "${field}" in
        *.*.*.*)
          ipv4_addr="${field}"
          ;;
      esac
      if [ -n "${ipv4_addr}" ]; then
        break
      fi
    done
    if [ -n "${ipv4_addr}" ]; then
      break
    fi
  done <<__RES__
${output}
__RES__

  if [ -n "${EXPECTED_IPV4}" ] && [ "${ipv4_addr}" != "${EXPECTED_IPV4}" ]; then
    return 2
  fi

  printf '%s|%s' "${any_addr}" "${ipv4_addr}"
  return 0
}

resolve_self_ipv4() {
  local host="$1"
  local expected_ipv4="${2:-}"

  if [ -z "${host}" ]; then
    return 3
  fi
  if ! command -v avahi-resolve >/dev/null 2>&1; then
    return 3
  fi

  local output
  if ! output="$(run_command_capture avahi_resolve_self avahi-resolve -4 -n "${host}")"; then
    return 1
  fi

  local ipv4
  ipv4="$(printf '%s\n' "${output}" | awk '{ for (i = NF; i >= 1; i--) { if ($i ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) { print $i; exit } } }' 2>/dev/null | tr -d '\r' | head -n1)"

  if [ -z "${ipv4}" ]; then
    return 1
  fi

  MDNS_LAST_CMD_PARSED_IPV4="${ipv4}"

  if [ -n "${expected_ipv4}" ] && [ "${ipv4}" != "${expected_ipv4}" ]; then
    printf '%s' "${ipv4}"
    return 2
  fi

  printf '%s' "${ipv4}"
  return 0
}

self_resolve_log() {
  local stage="$1"
  local attempt="$2"
  local outcome="fail"
  case "${SELF_RESOLVE_STATUS}" in
    0) outcome="ok" ;;
    3) outcome="skip" ;;
  esac
  local command_kv=""
  local duration_kv=""
  if [ -n "${SELF_RESOLVE_COMMAND}" ]; then
    command_kv="command=\"$(kv_escape "${SELF_RESOLVE_COMMAND}")\""
  fi
  if [ -n "${SELF_RESOLVE_DURATION}" ]; then
    duration_kv="command_duration_ms=${SELF_RESOLVE_DURATION}"
  fi
  if [ -n "${command_kv}" ] && [ -n "${duration_kv}" ]; then
    log_debug mdns_self_resolve stage="${stage}" attempt="${attempt}" outcome="${outcome}" reason="${SELF_RESOLVE_REASON}" "${command_kv}" "${duration_kv}"
  elif [ -n "${command_kv}" ]; then
    log_debug mdns_self_resolve stage="${stage}" attempt="${attempt}" outcome="${outcome}" reason="${SELF_RESOLVE_REASON}" "${command_kv}"
  elif [ -n "${duration_kv}" ]; then
    log_debug mdns_self_resolve stage="${stage}" attempt="${attempt}" outcome="${outcome}" reason="${SELF_RESOLVE_REASON}" "${duration_kv}"
  else
    log_debug mdns_self_resolve stage="${stage}" attempt="${attempt}" outcome="${outcome}" reason="${SELF_RESOLVE_REASON}"
  fi
}

self_resolve_attempt() {
  local stage="$1"
  local attempt="$2"

  SELF_RESOLVE_STATUS=3
  SELF_RESOLVE_HOST=""
  SELF_RESOLVE_IPV4=""
  SELF_RESOLVE_COMMAND=""
  SELF_RESOLVE_DURATION=""
  SELF_RESOLVE_REASON="skipped"

  if [ -z "${EXPECTED_IPV4}" ]; then
    self_resolve_log "${stage}" "${attempt}"
    return 3
  fi

  local host="${SELF_LOCAL_HOST:-}"
  if [ -z "${host}" ]; then
    self_resolve_log "${stage}" "${attempt}"
    return 3
  fi

  SELF_RESOLVE_HOST="${host}"

  local resolved
  if ! resolved="$(resolve_self_ipv4 "${host}" "${EXPECTED_IPV4}" 2>/dev/null)"; then
    local rc=$?
    SELF_RESOLVE_STATUS="${rc}"
    SELF_RESOLVE_COMMAND="${MDNS_LAST_CMD_DISPLAY:-}"
    SELF_RESOLVE_DURATION="${MDNS_LAST_CMD_DURATION_MS:-}"
    SELF_RESOLVE_IPV4="${MDNS_LAST_CMD_PARSED_IPV4:-}"
    case "${rc}" in
      2) SELF_RESOLVE_REASON="resolve_mismatch" ;;
      1) SELF_RESOLVE_REASON="resolve_unavailable" ;;
      3) SELF_RESOLVE_REASON="resolve_skipped" ;;
      *) SELF_RESOLVE_REASON="resolve_error" ;;
    esac
    self_resolve_log "${stage}" "${attempt}"
    return "${rc}"
  fi

  SELF_RESOLVE_STATUS=0
  SELF_RESOLVE_COMMAND="${MDNS_LAST_CMD_DISPLAY:-}"
  SELF_RESOLVE_DURATION="${MDNS_LAST_CMD_DURATION_MS:-}"
  SELF_RESOLVE_IPV4="${MDNS_LAST_CMD_PARSED_IPV4:-${resolved}}"
  SELF_RESOLVE_REASON="resolve_match"
  self_resolve_log "${stage}" "${attempt}"
  return 0
}

self_resolve_handle_success() {
  local attempt="$1"
  local stage="$2"

  local host="${SELF_RESOLVE_HOST:-}"
  if [ -z "${host}" ]; then
    host="${EXPECTED_HOST:-}"
  fi
  if [ -z "${host}" ]; then
    return 1
  fi

  local resolved_ipv4="${SELF_RESOLVE_IPV4:-${EXPECTED_IPV4}}"
  local resolved_any="${resolved_ipv4}"
  if [ -z "${resolved_any}" ]; then
    resolved_any="${EXPECTED_IPV4}"
  fi

  local command_kv=""
  local duration_kv=""
  if [ -n "${SELF_RESOLVE_COMMAND}" ]; then
    command_kv="command=\"$(kv_escape "${SELF_RESOLVE_COMMAND}")\""
  fi
  if [ -n "${SELF_RESOLVE_DURATION}" ]; then
    duration_kv="command_duration_ms=${SELF_RESOLVE_DURATION}"
  fi

  local elapsed_ms
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}" 2>/dev/null || printf '%s' 0)"
  case "${elapsed_ms}" in
    ''|*[!0-9]*) elapsed_ms=0 ;;
  esac

  local nss_ok=0
  local nss_rc=1
  if mdns_check_nss_host "${host}" "${EXPECTED_IPV4}" >/dev/null 2>&1; then
    nss_ok=1
    nss_rc=0
  else
    nss_rc=$?
  fi
  if [ "${nss_rc}" -eq 2 ]; then
    log_debug mdns_selfcheck_nss attempt="${attempt}" host="${host}" outcome=mismatch expected_ipv4="${EXPECTED_IPV4}" >&2
  fi
  MDNS_RESOLUTION_STATUS_NSS="${nss_ok}"
  MDNS_RESOLUTION_STATUS_RESOLVE=1

  local readiness_required=0
  if [ "${EXPECTED_ROLE}" = "server" ] || [ "${EXPECTED_PHASE}" = "server" ]; then
    readiness_required=1
  fi

  local srv_port="${EXPECTED_PORT}"
  local server_host="${EXPECTED_HOST:-${host}}"
  local resolve_method="avahi_resolve"

  if [ "${readiness_required}" -eq 1 ]; then
    local socket_targets
    socket_targets="$(build_socket_targets "${server_host}" "${resolved_ipv4}" "${resolved_any}")"
    if server_socket_ready "${server_host}" "${resolved_any}" "${resolved_ipv4}"; then
      local socket_status="${MDNS_SOCKET_CHECK_STATUS:-ok}"
      local socket_method="${MDNS_SOCKET_CHECK_METHOD:-unknown}"
      [ -n "${socket_status}" ] || socket_status="ok"
      [ -n "${socket_method}" ] || socket_method="unknown"
      local targets_kv
      targets_kv="targets=\"$(kv_escape "${socket_targets}")\""
      log_trace mdns_selfcheck_socket attempt="${attempt}" host="${server_host}" port="${srv_port}" status="${socket_status}" method="${socket_method}" "${targets_kv}"
      if [ -n "${command_kv}" ] && [ -n "${duration_kv}" ]; then
        mdns_resolution_status_emit ok attempt="${attempt}" host="${server_host}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}" "${command_kv}" "${duration_kv}"
        log_info mdns_selfcheck outcome=confirmed check=self_resolve host="${server_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}" "${command_kv}" "${duration_kv}"
      elif [ -n "${command_kv}" ]; then
        mdns_resolution_status_emit ok attempt="${attempt}" host="${server_host}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}" "${command_kv}"
        log_info mdns_selfcheck outcome=confirmed check=self_resolve host="${server_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}" "${command_kv}"
      elif [ -n "${duration_kv}" ]; then
        mdns_resolution_status_emit ok attempt="${attempt}" host="${server_host}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}" "${duration_kv}"
        log_info mdns_selfcheck outcome=confirmed check=self_resolve host="${server_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}" "${duration_kv}"
      else
        mdns_resolution_status_emit ok attempt="${attempt}" host="${server_host}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}"
        log_info mdns_selfcheck outcome=confirmed check=self_resolve host="${server_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" readiness_method="${socket_method}" stage="${stage}"
      fi
      return 0
    fi

    local socket_status="${MDNS_SOCKET_CHECK_STATUS:-fail}"
    local socket_method="${MDNS_SOCKET_CHECK_METHOD:-unknown}"
    [ -n "${socket_status}" ] || socket_status="fail"
    [ -n "${socket_method}" ] || socket_method="unknown"
    local targets_kv
    targets_kv="targets=\"$(kv_escape "$(build_socket_targets "${server_host}" "${resolved_ipv4}" "${resolved_any}")")\""
    log_trace mdns_selfcheck_socket attempt="${attempt}" host="${server_host}" port="${srv_port}" status="${socket_status}" method="${socket_method}" "${targets_kv}"
    if [ "${socket_status}" = "skipped" ]; then
      SELF_RESOLVE_REASON="server_socket_unchecked"
    else
      SELF_RESOLVE_REASON="server_socket_unready"
    fi
    return 1
  fi

  if [ -n "${command_kv}" ] && [ -n "${duration_kv}" ]; then
    mdns_resolution_status_emit ok attempt="${attempt}" host="${host}" resolve_method="${resolve_method}" stage="${stage}" "${command_kv}" "${duration_kv}"
    log_info mdns_selfcheck outcome=ok host="${host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" stage="${stage}" "${command_kv}" "${duration_kv}"
  elif [ -n "${command_kv}" ]; then
    mdns_resolution_status_emit ok attempt="${attempt}" host="${host}" resolve_method="${resolve_method}" stage="${stage}" "${command_kv}"
    log_info mdns_selfcheck outcome=ok host="${host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" stage="${stage}" "${command_kv}"
  elif [ -n "${duration_kv}" ]; then
    mdns_resolution_status_emit ok attempt="${attempt}" host="${host}" resolve_method="${resolve_method}" stage="${stage}" "${duration_kv}"
    log_info mdns_selfcheck outcome=ok host="${host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" stage="${stage}" "${duration_kv}"
  else
    mdns_resolution_status_emit ok attempt="${attempt}" host="${host}" resolve_method="${resolve_method}" stage="${stage}"
    log_info mdns_selfcheck outcome=ok host="${host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolve_method}" stage="${stage}"
  fi
  return 0
}

mdns_liveness_probe() {
  local host="${SELF_LOCAL_HOST:-}"
  local signal="liveness"

  if command -v gdbus >/dev/null 2>&1; then
    local dbus_output
    if dbus_output="$(run_command_capture avahi_dbus_hostname gdbus call --system --dest org.freedesktop.Avahi --object-path / --method org.freedesktop.Avahi.Server.GetHostNameFqdn)"; then
      local dbus_command_kv
      dbus_command_kv="command=\"$(kv_escape "${MDNS_LAST_CMD_DISPLAY:-}")\""
      local dbus_duration_kv
      dbus_duration_kv="command_duration_ms=${MDNS_LAST_CMD_DURATION_MS:-0}"
      local dbus_value
      dbus_value="$(printf '%s' "${dbus_output}" | tr '\n' ' ' | sed 's/"/\\"/g')"
      log_debug mdns_liveness outcome=ok signal=dbus_hostname "${dbus_command_kv}" "${dbus_duration_kv}" "output=\"${dbus_value}\""
    else
      local rc="${MDNS_LAST_CMD_RC:-1}"
      local dbus_command_kv
      dbus_command_kv="command=\"$(kv_escape "${MDNS_LAST_CMD_DISPLAY:-}")\""
      local dbus_duration_kv
      dbus_duration_kv="command_duration_ms=${MDNS_LAST_CMD_DURATION_MS:-0}"
      log_debug mdns_liveness outcome=lag signal=dbus_hostname rc="${rc}" "${dbus_command_kv}" "${dbus_duration_kv}"
    fi
  else
    log_debug mdns_liveness outcome=skip signal=dbus_hostname reason=gdbus_missing
  fi

  if [ -n "${host}" ] && [ -n "${EXPECTED_IPV4}" ]; then
    self_resolve_attempt "${signal}" 0 >/dev/null 2>&1 || true
  else
    log_debug mdns_liveness outcome=skip signal=self_resolve reason=missing_context
  fi
}

resolve_srv_target_cli() {
  local target="$1"
  local expected_ipv4="$2"

  if [ -z "${target}" ] || [ -z "${expected_ipv4}" ]; then
    return 3
  fi

  if ! command -v avahi-resolve-host-name >/dev/null 2>&1; then
    return 3
  fi

  local output
  if ! output="$(avahi-resolve-host-name "${target}" -4 --timeout=2 2>/dev/null)"; then
    return 1
  fi

  local ipv4
  ipv4="$(printf '%s\n' "${output}" | awk 'NF >= 2 { print $2; exit }' 2>/dev/null | tr -d '\r')"

  if [ -z "${ipv4}" ]; then
    return 1
  fi

  if [ "${ipv4}" != "${expected_ipv4}" ]; then
    return 2
  fi

  printf '%s' "${ipv4}"
  return 0
}

build_socket_targets() {
  host="$1"
  ipv4="$2"
  any="$3"
  result=""
  for candidate in "${host}" "${ipv4}" "${any}"; do
    [ -n "${candidate}" ] || continue
    case ",${result}," in
      *,"${candidate}",*)
        continue
        ;;
    esac
    if [ -n "${result}" ]; then
      result="${result},${candidate}"
    else
      result="${candidate}"
    fi
  done
  printf '%s' "${result}"
}

mdns_selfcheck__curl_probe() {
  target="$1"
  if [ -z "${CURL_BIN}" ]; then
    return 1
  fi
  url_host="${target}"
  case "${url_host}" in
    *:*)
      url_host="[${url_host}]"
      ;;
  esac
  "${CURL_BIN}" --connect-timeout 2 --max-time 5 -ksS -o /dev/null \
    "https://${url_host}:6443/livez" >/dev/null 2>&1
}

mdns_selfcheck__python_probe() {
  target="$1"
  python3 - "$target" <<'PY' >/dev/null 2>&1
import socket
import sys

host = sys.argv[1]

try:
    with socket.create_connection((host, 6443), timeout=2):
        pass
except Exception:
    sys.exit(1)

sys.exit(0)
PY
}

mdns_selfcheck__devtcp_probe() {
  target="$1"
  if [ -z "${TIMEOUT_BIN}" ] || [ -z "${BASH_BIN}" ]; then
    return 1
  fi
  case "${target}" in
    *:*)
      return 1
      ;;
  esac
  "${TIMEOUT_BIN}" 2 "${BASH_BIN}" -c "exec 3</dev/tcp/${target}/6443" >/dev/null 2>&1
}

server_socket_ready() {
  host="$1"
  any_addr="$2"
  ipv4_addr="$3"
  MDNS_SOCKET_CHECK_STATUS="fail"
  MDNS_SOCKET_CHECK_METHOD=""
  attempted=0
  seen=""
  for candidate in "${ipv4_addr}" "${host}" "${any_addr}"; do
    [ -n "${candidate}" ] || continue
    case " ${seen} " in
      *" ${candidate} "*)
        continue
        ;;
    esac
    seen="${seen} ${candidate}"
    if [ -n "${CURL_BIN}" ]; then
      attempted=1
      if mdns_selfcheck__curl_probe "${candidate}"; then
        MDNS_SOCKET_CHECK_STATUS="ok"
        MDNS_SOCKET_CHECK_METHOD="curl"
        return 0
      fi
      MDNS_SOCKET_CHECK_METHOD="curl"
    fi
    attempted=1
    if mdns_selfcheck__python_probe "${candidate}"; then
      MDNS_SOCKET_CHECK_STATUS="ok"
      MDNS_SOCKET_CHECK_METHOD="python"
      return 0
    fi
    MDNS_SOCKET_CHECK_METHOD="python"
    if [ -n "${TIMEOUT_BIN}" ] && [ -n "${BASH_BIN}" ]; then
      attempted=1
      if mdns_selfcheck__devtcp_probe "${candidate}"; then
        MDNS_SOCKET_CHECK_STATUS="ok"
        MDNS_SOCKET_CHECK_METHOD="devtcp"
        return 0
      fi
      MDNS_SOCKET_CHECK_METHOD="devtcp"
    fi
  done
  if [ "${attempted}" -eq 0 ]; then
    MDNS_SOCKET_CHECK_STATUS="skipped"
    MDNS_SOCKET_CHECK_METHOD=""
    return 2
  fi
  return 1
}

compute_delay_ms() {
  python3 - "$@" <<'PY'
import random
import sys

try:
    attempt = int(sys.argv[1])
except ValueError:
    attempt = 1
try:
    start = int(sys.argv[2])
except ValueError:
    start = 0
try:
    cap = int(sys.argv[3])
except ValueError:
    cap = 0
try:
    jitter = float(sys.argv[4])
except ValueError:
    jitter = 0.0

if attempt < 1:
    attempt = 1
if start < 0:
    start = 0
if cap < 0:
    cap = 0
if cap and start > cap:
    base = cap
else:
    base = start * (2 ** (attempt - 1)) if attempt > 0 else start
if cap and base > cap:
    base = cap
if jitter > 0:
    low = max(0.0, 1.0 - jitter)
    high = 1.0 + jitter
    factor = random.uniform(low, high)
    delay = int(base * factor)
else:
    delay = base
if delay < 0:
    delay = 0
print(delay)
PY
}

mdns_selfcheck__service_type_check() {
  local type_output type_present available_types available_kv available_escaped available_seen
  local active_window_ms active_start_elapsed current_elapsed delta_ms remaining_ms sleep_seconds
  local active_output active_count active_found active_attempts

  type_output="$(run_command_capture mdns_browse_types avahi-browse --parsable --terminate _services._dns-sd._udp || true)"
  type_command="${MDNS_LAST_CMD_DISPLAY:-}"
  type_duration="${MDNS_LAST_CMD_DURATION_MS:-}"
  type_present=0
  available_types=""
  available_seen=","
  if [ -n "${type_output}" ]; then
    local old_ifs field browse_line
    old_ifs="${IFS}"
    while IFS= read -r browse_line; do
      [ -n "${browse_line}" ] || continue
      IFS=';'
      # shellcheck disable=SC2086
      set -- ${browse_line}
      IFS="${old_ifs}"
      for field in "$@"; do
        case "${field}" in
          "${SERVICE_TYPE}")
            type_present=1
            ;;
          _*._tcp|_*._udp)
            case "${available_seen}" in
              *,"${field}",*)
                ;;
              *)
                available_seen="${available_seen}${field},"
                if [ -n "${available_types}" ]; then
                  available_types="${available_types},${field}"
                else
                  available_types="${field}"
                fi
                ;;
            esac
            ;;
        esac
      done
    done <<__MDNS_TYPES__
${type_output}
__MDNS_TYPES__
    IFS="${old_ifs}"
  fi

  case "${type_present}" in
    1) type_present=1 ;;
    *) type_present=0 ;;
  esac
  available_kv=""
  if [ -n "${available_types}" ]; then
    available_escaped="$(printf '%s' "${available_types}" | sed 's/"/\\"/g')"
    available_kv="available_types=\"${available_escaped}\""
  fi

  type_command_kv=""
  type_duration_kv=""
  if [ -n "${type_command}" ]; then
    type_command_kv="command=\"$(kv_escape "${type_command}")\""
  fi
  if [ -n "${type_duration}" ]; then
    type_duration_kv="command_duration_ms=${type_duration}"
  fi

  if [ "${type_present}" -eq 1 ]; then
    if [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}" \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}" \
        "${type_command_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${available_kv}"
    elif [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${type_command_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${type_command_kv}"
    elif [ -n "${type_duration_kv}" ]; then
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}" \
        "${type_duration_kv}"
    else
      log_debug mdns_selfcheck event=mdns_type_check \
        present="${type_present}" \
        service_type="${SERVICE_TYPE}"
    fi
  else
    if [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}" \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_command_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}" \
        "${type_command_kv}"
    elif [ -n "${available_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}" \
        "${type_duration_kv}"
    elif [ -n "${available_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${available_kv}"
    elif [ -n "${type_command_kv}" ] && [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${type_command_kv}" \
        "${type_duration_kv}"
    elif [ -n "${type_command_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${type_command_kv}"
    elif [ -n "${type_duration_kv}" ]; then
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn \
        "${type_duration_kv}"
    else
      log_info mdns_type_check present="${type_present}" service_type="${SERVICE_TYPE}" severity=warn
    fi
  fi

  active_window_ms="${ACTIVE_QUERY_WINDOW_MS}"
  case "${active_window_ms}" in
    ''|*[!0-9]*) active_window_ms=0 ;;
  esac

  active_start_elapsed="$(elapsed_since_start_ms "${script_start_ms}")"
  case "${active_start_elapsed}" in
    ''|*[!0-9]*) active_start_elapsed=0 ;;
  esac

  active_attempts=0
  active_found=0
  INITIAL_BROWSE_OUTPUT=""
  INITIAL_BROWSE_READY=0

  if [ "${type_present}" -eq 0 ]; then
    while :; do
      active_attempts=$((active_attempts + 1))
      active_output="$(run_command_capture mdns_browse_active avahi-browse --parsable --resolve --terminate "${SERVICE_TYPE}" || true)"
      active_command="${MDNS_LAST_CMD_DISPLAY:-}"
      active_duration="${MDNS_LAST_CMD_DURATION_MS:-}"
      active_count="$(printf '%s\n' "${active_output}" | awk -v svc="${SERVICE_TYPE}" '
BEGIN { FS = ";"; count = 0 }
$1 == "=" {
  for (i = 1; i <= NF; i++) {
    if ($i == svc) {
      count++
      break
    }
  }
}
END { print count }
"' 2>/dev/null | tr -d '\n' | tr -d '\r')"
      case "${active_count}" in
        ''|*[!0-9]*) active_count=0 ;;
      esac

      if [ "${active_count}" -gt 0 ]; then
        INITIAL_BROWSE_OUTPUT="${active_output}"
        INITIAL_BROWSE_READY=1
        active_found=1
        log_debug mdns_selfcheck event=mdns_type_active outcome=hit attempts="${active_attempts}" instances="${active_count}"
        break
      fi

      if [ "${active_window_ms}" -le 0 ]; then
        INITIAL_BROWSE_OUTPUT="${active_output}"
        break
      fi

      current_elapsed="$(elapsed_since_start_ms "${script_start_ms}")"
      case "${current_elapsed}" in
        ''|*[!0-9]*) current_elapsed=0 ;;
      esac
      delta_ms=$((current_elapsed - active_start_elapsed))
      if [ "${delta_ms}" -lt 0 ]; then
        delta_ms=0
      fi
      if [ "${delta_ms}" -ge "${active_window_ms}" ]; then
        INITIAL_BROWSE_OUTPUT="${active_output}"
        break
      fi

      remaining_ms=$((active_window_ms - delta_ms))
      if [ "${remaining_ms}" -le 0 ]; then
        break
      fi

      if [ "${remaining_ms}" -gt 1000 ]; then
        sleep_seconds=1
      else
        sleep_seconds="$({
          python3 - <<'PY' "${remaining_ms}"
import sys
try:
    delay = int(sys.argv[1])
except ValueError:
    delay = 0
print('{:.3f}'.format(delay / 1000.0))
PY
        } 2>/dev/null)"
        if [ -z "${sleep_seconds}" ]; then
          sleep_seconds=0
        fi
        case "${sleep_seconds}" in
          0|0.0|0.00|0.000) sleep_seconds=0 ;;
        esac
      fi

      if [ "${sleep_seconds}" = "0" ] || [ -z "${sleep_seconds}" ]; then
        sleep 1
      else
        sleep "${sleep_seconds}"
      fi
    done

    if [ "${active_found}" -ne 1 ]; then
      elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
      case "${elapsed_ms}" in
        ''|*[!0-9]*) elapsed_ms=0 ;;
      esac
      active_command_kv=""
      active_duration_kv=""
      if [ -n "${active_command}" ]; then
        active_command_kv="command=\"$(kv_escape "${active_command}")\""
      fi
      if [ -n "${active_duration}" ]; then
        active_duration_kv="command_duration_ms=${active_duration}"
      fi
      if [ -n "${active_command_kv}" ] && [ -n "${active_duration_kv}" ]; then
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}" "${active_command_kv}" "${active_duration_kv}"
      elif [ -n "${active_command_kv}" ]; then
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}" "${active_command_kv}"
      elif [ -n "${active_duration_kv}" ]; then
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}" "${active_duration_kv}"
      else
        log_debug mdns_selfcheck event=mdns_type_active outcome=miss service_type="${SERVICE_TYPE}" attempts="${active_attempts}" ms_elapsed="${elapsed_ms}"
      fi
    fi
  fi
}

mdns_liveness_probe

mdns_selfcheck__service_type_check

attempt=1
last_reason=""
miss_count=0
while [ "${attempt}" -le "${ATTEMPTS}" ]; do
  # Use parsable semicolon-delimited output with resolution and terminate flags
  MDNS_LAST_FAILURE_COMMAND=""
  MDNS_LAST_FAILURE_DURATION=""
  if [ "${INITIAL_BROWSE_READY}" -eq 1 ]; then
    browse_output="${INITIAL_BROWSE_OUTPUT}"
    browse_command="${active_command:-}"
    browse_duration="${active_duration:-}"
    INITIAL_BROWSE_READY=0
  else
    browse_output="$(run_command_capture mdns_browse avahi-browse --parsable --resolve --terminate "${SERVICE_TYPE}" || true)"
    browse_command="${MDNS_LAST_CMD_DISPLAY:-}"
    browse_duration="${MDNS_LAST_CMD_DURATION_MS:-}"
  fi
  parsed="$(printf '%s\n' "${browse_output}" | parse_browse || true)"
  browse_for_trace="$(printf '%s' "${browse_output}" | tr '\n' ' ' | tr -s ' ' | sed 's/"/\\"/g')"
  browse_command_kv=""
  browse_duration_kv=""
  if [ -n "${browse_command}" ]; then
    browse_command_kv="command=\"$(kv_escape "${browse_command}")\""
  fi
  if [ -n "${browse_duration}" ]; then
    browse_duration_kv="command_duration_ms=${browse_duration}"
  fi
  if [ -n "${browse_command_kv}" ] && [ -n "${browse_duration_kv}" ]; then
    log_trace mdns_selfcheck_browse attempt="${attempt}" "raw=\"${browse_for_trace}\"" "${browse_command_kv}" "${browse_duration_kv}"
  elif [ -n "${browse_command_kv}" ]; then
    log_trace mdns_selfcheck_browse attempt="${attempt}" "raw=\"${browse_for_trace}\"" "${browse_command_kv}"
  elif [ -n "${browse_duration_kv}" ]; then
    log_trace mdns_selfcheck_browse attempt="${attempt}" "raw=\"${browse_for_trace}\"" "${browse_duration_kv}"
  else
    log_trace mdns_selfcheck_browse attempt="${attempt}" "raw=\"${browse_for_trace}\""
  fi
  if [ -n "${parsed}" ]; then
    handshake_failed=0
    srv_host="${parsed#*|}"
    srv_host="${srv_host%%|*}"
    srv_port="${parsed##*|}"
    if [ -z "${srv_host}" ]; then
      last_reason="empty_srv_host"
    else
      host_matches=1
      if [ "${HOSTNAME_CHECK_ENABLED}" -eq 1 ]; then
        if ! host_matches_self "${srv_host}"; then
          host_matches=0
          last_reason="srv_target_mismatch"
          log_trace mdns_selfcheck_host attempt="${attempt}" host="${srv_host}" outcome=skip reason="${last_reason}"
        fi
      fi
      if [ "${host_matches}" -eq 1 ]; then
        MDNS_RESOLUTION_STATUS_BROWSE=1
        nss_ok=0
        nss_rc=1
        if mdns_check_nss_host "${srv_host}" "${EXPECTED_IPV4}" >/dev/null 2>&1; then
          nss_ok=1
          nss_rc=0
        else
          nss_rc=$?
        fi
        if [ "${nss_rc}" -eq 2 ]; then
          log_debug mdns_selfcheck_nss attempt="${attempt}" host="${srv_host}" outcome=mismatch expected_ipv4="${EXPECTED_IPV4}" >&2
        fi
        MDNS_RESOLUTION_STATUS_NSS="${nss_ok}"
        cli_status=3
        cli_ipv4=""
        if [ -n "${EXPECTED_IPV4}" ]; then
          if cli_ipv4="$(resolve_srv_target_cli "${srv_host}" "${EXPECTED_IPV4}" 2>/dev/null)"; then
            cli_status=0
          else
            cli_status=$?
          fi
        fi
        cli_ipv4_for_trace="$(printf '%s' "${cli_ipv4}" | tr '\n' ' ' | sed 's/"/\\"/g')"
        log_trace mdns_selfcheck_cli attempt="${attempt}" host="${srv_host}" status="${cli_status}" "ipv4=\"${cli_ipv4_for_trace}\""
        if [ "${cli_status}" -eq 2 ]; then
          last_reason="ipv4_mismatch"
          log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}"
          elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
          log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}"
          mdns_resolution_status_emit fail attempt="${attempt}" host="${srv_host}" reason="${last_reason}"
          exit 5
        fi

        resolved=""
        status=1
        resolution_method="avahi"
        if [ "${cli_status}" -eq 0 ]; then
          resolved="${cli_ipv4}|${cli_ipv4}"
          status=0
          resolution_method="cli"
        else
          resolved="$(resolve_host "${srv_host}" || true)"
          status=$?
        fi
        resolved_for_trace="$(printf '%s' "${resolved}" | tr '\n' ' ' | sed 's/"/\\"/g')"
        log_trace mdns_selfcheck_resolve attempt="${attempt}" host="${srv_host}" status="${status}" method="${resolution_method}" "resolved=\"${resolved_for_trace}\""

        if [ "${status}" -eq 0 ]; then
          MDNS_RESOLUTION_STATUS_RESOLVE=1
        else
          MDNS_RESOLUTION_STATUS_RESOLVE=0
        fi

        if [ "${status}" -eq 0 ] && [ -n "${resolved}" ]; then
          resolved_ipv4="${resolved##*|}"
          resolved_any="${resolved%%|*}"
          elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
          readiness_required=0
          if [ "${EXPECTED_ROLE}" = "server" ] || [ "${EXPECTED_PHASE}" = "server" ]; then
            readiness_required=1
          fi

          if [ "${cli_status}" -eq 0 ] && [ "${readiness_required}" -ne 1 ]; then
            mdns_resolution_status_emit ok attempt="${attempt}" host="${srv_host}" resolve_method="${resolution_method}"
            log_info mdns_selfcheck outcome=confirmed check=cli host="${srv_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolution_method}"
            exit 0
          fi

          socket_targets="$(build_socket_targets "${srv_host}" "${resolved_ipv4}" "${resolved_any}")"
          socket_targets_escaped="$(printf '%s' "${socket_targets}" | sed 's/"/\\"/g')"
          if [ "${readiness_required}" -eq 1 ]; then
            if server_socket_ready "${srv_host}" "${resolved_any}" "${resolved_ipv4}"; then
              socket_status="${MDNS_SOCKET_CHECK_STATUS:-ok}"
              socket_method="${MDNS_SOCKET_CHECK_METHOD:-unknown}"
              [ -n "${socket_method}" ] || socket_method="unknown"
              [ -n "${socket_status}" ] || socket_status="ok"
              log_trace mdns_selfcheck_socket attempt="${attempt}" host="${srv_host}" port="${srv_port}" status="${socket_status}" method="${socket_method}" "targets=\"${socket_targets_escaped}\""
              mdns_resolution_status_emit ok attempt="${attempt}" host="${srv_host}" resolve_method="${resolution_method}" readiness_method="${socket_method}"
              log_info mdns_selfcheck outcome=confirmed check=server host="${srv_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" readiness_method="${socket_method}" readiness_targets="${socket_targets}" resolve_method="${resolution_method}"
              exit 0
            fi
            handshake_failed=1
            socket_status="${MDNS_SOCKET_CHECK_STATUS:-fail}"
            socket_method="${MDNS_SOCKET_CHECK_METHOD:-unknown}"
            [ -n "${socket_method}" ] || socket_method="unknown"
            [ -n "${socket_status}" ] || socket_status="fail"
            log_trace mdns_selfcheck_socket attempt="${attempt}" host="${srv_host}" port="${srv_port}" status="${socket_status}" method="${socket_method}" "targets=\"${socket_targets_escaped}\""
            if [ "${socket_status}" = "skipped" ]; then
              last_reason="server_socket_unchecked"
            else
              last_reason="server_socket_unready"
            fi
            MDNS_LAST_FAILURE_COMMAND="${browse_command:-}"
            MDNS_LAST_FAILURE_DURATION="${browse_duration:-}"
          else
            mdns_resolution_status_emit ok attempt="${attempt}" host="${srv_host}" resolve_method="${resolution_method}"
            log_info mdns_selfcheck outcome=ok host="${srv_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" resolve_method="${resolution_method}"
            exit 0
          fi
        fi
        if [ "${status}" -eq 2 ]; then
          # IPv4 mismatch: signal to caller explicitly and avoid unnecessary retries
          last_reason="ipv4_mismatch"
          log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}"
          elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
          MDNS_LAST_FAILURE_COMMAND="${browse_command:-}"
          MDNS_LAST_FAILURE_DURATION="${browse_duration:-}"
          fail_command_kv=""
          fail_duration_kv=""
          if [ -n "${MDNS_LAST_FAILURE_COMMAND}" ]; then
            fail_command_kv="command=\"$(kv_escape "${MDNS_LAST_FAILURE_COMMAND}")\""
          fi
          if [ -n "${MDNS_LAST_FAILURE_DURATION}" ]; then
            fail_duration_kv="command_duration_ms=${MDNS_LAST_FAILURE_DURATION}"
          fi
          if [ -n "${fail_command_kv}" ] && [ -n "${fail_duration_kv}" ]; then
            log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${fail_command_kv}" "${fail_duration_kv}"
          elif [ -n "${fail_command_kv}" ]; then
            log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${fail_command_kv}"
          elif [ -n "${fail_duration_kv}" ]; then
            log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${fail_duration_kv}"
          else
            log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}"
          fi
          exit 5
        elif [ "${status}" -eq 0 ] && [ "${handshake_failed}" -eq 1 ]; then
          :
        else
          last_reason="resolve_failed"
          MDNS_LAST_FAILURE_COMMAND="${browse_command:-}"
          MDNS_LAST_FAILURE_DURATION="${browse_duration:-}"
        fi
      fi
    fi
  else
    if [ -z "${browse_output}" ]; then
      browse_reason="browse_empty"
    else
      browse_reason="instance_not_found"
    fi
    MDNS_LAST_FAILURE_COMMAND="${browse_command:-}"
    MDNS_LAST_FAILURE_DURATION="${browse_duration:-}"
    if self_resolve_attempt browse "${attempt}" >/dev/null 2>&1; then
      :
    fi
    case "${SELF_RESOLVE_STATUS}" in
      0)
        if self_resolve_handle_success "${attempt}" "browse"; then
          exit 0
        fi
        MDNS_LAST_FAILURE_COMMAND="${SELF_RESOLVE_COMMAND:-${browse_command:-}}"
        MDNS_LAST_FAILURE_DURATION="${SELF_RESOLVE_DURATION:-${browse_duration:-}}"
        if [ -n "${SELF_RESOLVE_REASON}" ]; then
          last_reason="${SELF_RESOLVE_REASON}"
        else
          last_reason="${browse_reason}"
        fi
        ;;
      2)
        MDNS_LAST_FAILURE_COMMAND="${SELF_RESOLVE_COMMAND:-${browse_command:-}}"
        MDNS_LAST_FAILURE_DURATION="${SELF_RESOLVE_DURATION:-${browse_duration:-}}"
        last_reason="resolve_mismatch"
        elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
        case "${elapsed_ms}" in
          ''|*[!0-9]*) elapsed_ms=0 ;;
        esac
        mismatch_command_kv=""
        mismatch_duration_kv=""
        if [ -n "${SELF_RESOLVE_COMMAND}" ]; then
          mismatch_command_kv="command=\"$(kv_escape "${SELF_RESOLVE_COMMAND}")\""
        fi
        if [ -n "${SELF_RESOLVE_DURATION}" ]; then
          mismatch_duration_kv="command_duration_ms=${SELF_RESOLVE_DURATION}"
        fi
        if [ -n "${mismatch_command_kv}" ] && [ -n "${mismatch_duration_kv}" ]; then
          log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${mismatch_command_kv}" "${mismatch_duration_kv}"
        elif [ -n "${mismatch_command_kv}" ]; then
          log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${mismatch_command_kv}"
        elif [ -n "${mismatch_duration_kv}" ]; then
          log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${mismatch_duration_kv}"
        else
          log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}"
        fi
        mdns_resolution_status_emit fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}"
        exit 5
        ;;
      *)
        if [ -n "${SELF_RESOLVE_REASON}" ] && [ "${SELF_RESOLVE_STATUS}" -ne 3 ]; then
          last_reason="${SELF_RESOLVE_REASON}"
        else
          last_reason="${browse_reason}"
        fi
        ;;
    esac
  fi

  miss_count=$((miss_count + 1))
  miss_command_kv=""
  miss_duration_kv=""
  if [ -n "${MDNS_LAST_FAILURE_COMMAND}" ]; then
    miss_command_kv="command=\"$(kv_escape "${MDNS_LAST_FAILURE_COMMAND}")\""
  fi
  if [ -n "${MDNS_LAST_FAILURE_DURATION}" ]; then
    miss_duration_kv="command_duration_ms=${MDNS_LAST_FAILURE_DURATION}"
  fi
  if [ -n "${miss_command_kv}" ] && [ -n "${miss_duration_kv}" ]; then
    log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}" "${miss_command_kv}" "${miss_duration_kv}"
  elif [ -n "${miss_command_kv}" ]; then
    log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}" "${miss_command_kv}"
  elif [ -n "${miss_duration_kv}" ]; then
    log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}" "${miss_duration_kv}"
  else
    log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}"
  fi

  if [ "${attempt}" -ge "${ATTEMPTS}" ]; then
    break
  fi

  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  case "${elapsed_ms}" in
    ''|*[!0-9]*) elapsed_ms=0 ;;
  esac

  delay_ms=0
  delay_mode="backoff"
  use_backoff_delay=1

  if [ "${ACTIVE_QUERY_ENABLED}" -eq 1 ] && [ "${ACTIVE_QUERY_WINDOW_MS}" -gt 0 ]; then
    if [ "${elapsed_ms}" -lt "${ACTIVE_QUERY_WINDOW_MS}" ]; then
      target_ms=""
      case "${attempt}" in
        1) target_ms=1000 ;;
        2) target_ms=3000 ;;
        3) target_ms="${ACTIVE_QUERY_WINDOW_MS}" ;;
        *) target_ms="" ;;
      esac
      if [ -n "${target_ms}" ]; then
        if [ "${target_ms}" -gt "${ACTIVE_QUERY_WINDOW_MS}" ]; then
          target_ms="${ACTIVE_QUERY_WINDOW_MS}"
        fi
        delay_ms=$((target_ms - elapsed_ms))
        if [ "${delay_ms}" -lt 0 ]; then
          delay_ms=0
        fi
        delay_mode="active"
        use_backoff_delay=0
        if [ "${target_ms}" -ge "${ACTIVE_QUERY_WINDOW_MS}" ]; then
          ACTIVE_QUERY_ENABLED=0
        fi
      else
        ACTIVE_QUERY_ENABLED=0
      fi
    else
      ACTIVE_QUERY_ENABLED=0
    fi
  fi

  if [ "${use_backoff_delay}" -eq 1 ]; then
    delay_ms="$(compute_delay_ms "${attempt}" "${BACKOFF_START_MS}" "${BACKOFF_CAP_MS}" "${JITTER_FRACTION}" || echo 0)"
  fi
  case "${delay_ms}" in
    ''|*[!0-9]*) delay_ms=0 ;;
  esac
  if [ "${delay_ms}" -gt 0 ]; then
    delay_s="$(
      python3 - "${delay_ms}" <<'PY'
import sys
try:
    delay = int(sys.argv[1])
except ValueError:
    delay = 0
print('{:.3f}'.format(delay / 1000.0))
PY
    )"
    log_trace mdns_selfcheck_backoff attempt="${attempt}" delay_ms="${delay_ms}" delay_s="${delay_s}" mode="${delay_mode}"
    sleep "${delay_s}"
  fi
  attempt=$((attempt + 1))
done

elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
if [ "${MDNS_RESOLUTION_STATUS_BROWSE}" = "1" ] && [ "${MDNS_RESOLUTION_STATUS_RESOLVE}" = "0" ] && [ "${last_reason}" = "resolve_failed" ]; then
  warn_command_kv=""
  warn_duration_kv=""
  if [ -n "${MDNS_LAST_FAILURE_COMMAND}" ]; then
    warn_command_kv="command=\"$(kv_escape "${MDNS_LAST_FAILURE_COMMAND}")\""
  fi
  if [ -n "${MDNS_LAST_FAILURE_DURATION}" ]; then
    warn_duration_kv="command_duration_ms=${MDNS_LAST_FAILURE_DURATION}"
  fi
  if [ -n "${warn_command_kv}" ] && [ -n "${warn_duration_kv}" ]; then
    mdns_resolution_status_emit warn attempts="${ATTEMPTS}" misses="${miss_count}" ms_elapsed="${elapsed_ms}" host="${EXPECTED_HOST}" "${warn_command_kv}" "${warn_duration_kv}"
    log_info mdns_selfcheck outcome=warn attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${warn_command_kv}" "${warn_duration_kv}"
  elif [ -n "${warn_command_kv}" ]; then
    mdns_resolution_status_emit warn attempts="${ATTEMPTS}" misses="${miss_count}" ms_elapsed="${elapsed_ms}" host="${EXPECTED_HOST}" "${warn_command_kv}"
    log_info mdns_selfcheck outcome=warn attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${warn_command_kv}"
  elif [ -n "${warn_duration_kv}" ]; then
    mdns_resolution_status_emit warn attempts="${ATTEMPTS}" misses="${miss_count}" ms_elapsed="${elapsed_ms}" host="${EXPECTED_HOST}" "${warn_duration_kv}"
    log_info mdns_selfcheck outcome=warn attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${warn_duration_kv}"
  else
    mdns_resolution_status_emit warn attempts="${ATTEMPTS}" misses="${miss_count}" ms_elapsed="${elapsed_ms}" host="${EXPECTED_HOST}"
    log_info mdns_selfcheck outcome=warn attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}"
  fi
  exit 0
fi
fail_command_kv=""
fail_duration_kv=""
if [ -n "${MDNS_LAST_FAILURE_COMMAND}" ]; then
  fail_command_kv="command=\"$(kv_escape "${MDNS_LAST_FAILURE_COMMAND}")\""
fi
if [ -n "${MDNS_LAST_FAILURE_DURATION}" ]; then
  fail_duration_kv="command_duration_ms=${MDNS_LAST_FAILURE_DURATION}"
fi
if [ -n "${fail_command_kv}" ] && [ -n "${fail_duration_kv}" ]; then
  log_info mdns_selfcheck outcome=fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" "${fail_command_kv}" "${fail_duration_kv}"
  mdns_resolution_status_emit fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" "${fail_command_kv}" "${fail_duration_kv}"
elif [ -n "${fail_command_kv}" ]; then
  log_info mdns_selfcheck outcome=fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" "${fail_command_kv}"
  mdns_resolution_status_emit fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" "${fail_command_kv}"
elif [ -n "${fail_duration_kv}" ]; then
  log_info mdns_selfcheck outcome=fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" "${fail_duration_kv}"
  mdns_resolution_status_emit fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" "${fail_duration_kv}"
else
  log_info mdns_selfcheck outcome=fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}"
  mdns_resolution_status_emit fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}"
fi

# Use a distinct exit code for IPv4 mismatch to enable targeted relaxed retries upstream
case "${last_reason}" in
  ipv4_mismatch)
    exit 5
    ;;
  *)
    exit 1
    ;;
esac
