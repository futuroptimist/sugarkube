#!/bin/sh
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
  log_info mdns_selfcheck_failure outcome=miss reason=missing_expected_host attempt=0 ms_elapsed="${elapsed_ms}" >&2
  exit 2
fi

dbus_mode="${SUGARKUBE_MDNS_DBUS:-auto}"
if [ "${dbus_mode}" != "0" ]; then
  dbus_script="${SCRIPT_DIR}/mdns_selfcheck_dbus.sh"
  if [ -x "${dbus_script}" ]; then
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

if ! command -v avahi-browse >/dev/null 2>&1; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck_failure outcome=miss reason=avahi_browse_missing attempt=0 ms_elapsed="${elapsed_ms}" >&2
  exit 3
fi
if ! command -v avahi-resolve >/dev/null 2>&1; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck_failure outcome=miss reason=avahi_resolve_missing attempt=0 ms_elapsed="${elapsed_ms}" >&2
  exit 3
fi

SERVICE_TYPE="_k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}._tcp"

# Accept both short host and FQDN in browse results
EXPECTED_SHORT_HOST="${EXPECTED_HOST%.local}"

parse_browse() {
  awk -v svc="${SERVICE_TYPE}" \
      -v expected_host="${EXPECTED_HOST}" \
      -v short_host="${EXPECTED_SHORT_HOST}" \
      -v expected_role="${EXPECTED_ROLE}" \
      -v expected_phase="${EXPECTED_PHASE}" \
      -v cluster="${SERVICE_CLUSTER}" \
      -v env="${SERVICE_ENV}" '
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
      gsub(/\\'/, "'", value)
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
  if ! output="$(avahi-resolve -n "${host}" 2>/dev/null)"; then
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

attempt=1
last_reason=""
miss_count=0
while [ "${attempt}" -le "${ATTEMPTS}" ]; do
  # Use parsable semicolon-delimited output with resolution and terminate flags
  browse_output="$(avahi-browse --parsable --resolve --terminate "${SERVICE_TYPE}" 2>/dev/null || true)"
  parsed="$(printf '%s\n' "${browse_output}" | parse_browse || true)"
  browse_for_trace="$(printf '%s' "${browse_output}" | tr '\n' ' ' | tr -s ' ' | sed 's/"/\\"/g')"
  log_trace mdns_selfcheck_browse attempt="${attempt}" "raw=\"${browse_for_trace}\""
  if [ -n "${parsed}" ]; then
    handshake_failed=0
    srv_host="${parsed#*|}"
    srv_host="${srv_host%%|*}"
    srv_port="${parsed##*|}"
    if [ -z "${srv_host}" ]; then
      last_reason="empty_srv_host"
    else
      resolved="$(resolve_host "${srv_host}" || true)"
      status=$?
      resolved_for_trace="$(printf '%s' "${resolved}" | tr '\n' ' ' | sed 's/"/\\"/g')"
      log_trace mdns_selfcheck_resolve attempt="${attempt}" host="${srv_host}" status="${status}" "resolved=\"${resolved_for_trace}\""
      if [ "${status}" -eq 0 ] && [ -n "${resolved}" ]; then
        resolved_ipv4="${resolved##*|}"
        resolved_any="${resolved%%|*}"
        elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
        readiness_required=0
        if [ "${EXPECTED_ROLE}" = "server" ] || [ "${EXPECTED_PHASE}" = "server" ]; then
          readiness_required=1
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
            log_info mdns_selfcheck outcome=confirmed check=server host="${srv_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}" readiness_method="${socket_method}" readiness_targets="${socket_targets}"
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
        else
          log_info mdns_selfcheck outcome=ok host="${srv_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${attempt}" ms_elapsed="${elapsed_ms}"
          exit 0
        fi
      fi
      if [ "${status}" -eq 2 ]; then
        # IPv4 mismatch: signal to caller explicitly and avoid unnecessary retries
        last_reason="ipv4_mismatch"
        log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}"
        elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
        log_info mdns_selfcheck outcome=fail attempts="${attempt}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" >&2
        exit 5
      elif [ "${status}" -eq 0 ] && [ "${handshake_failed}" -eq 1 ]; then
        :
      else
        last_reason="resolve_failed"
      fi
    fi
  else
    if [ -z "${browse_output}" ]; then
      last_reason="browse_empty"
    else
      last_reason="instance_not_found"
    fi
  fi

  miss_count=$((miss_count + 1))
  log_debug mdns_selfcheck outcome=miss attempt="${attempt}" reason="${last_reason}" service_type="${SERVICE_TYPE}"

  if [ "${attempt}" -ge "${ATTEMPTS}" ]; then
    break
  fi

  delay_ms="$(compute_delay_ms "${attempt}" "${BACKOFF_START_MS}" "${BACKOFF_CAP_MS}" "${JITTER_FRACTION}" || echo 0)"
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
    log_trace mdns_selfcheck_backoff attempt="${attempt}" delay_ms="${delay_ms}" delay_s="${delay_s}"
    sleep "${delay_s}"
  fi
  attempt=$((attempt + 1))
done

elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
log_info mdns_selfcheck outcome=fail attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason:-unknown}" ms_elapsed="${elapsed_ms}" >&2

# Use a distinct exit code for IPv4 mismatch to enable targeted relaxed retries upstream
case "${last_reason}" in
  ipv4_mismatch)
    exit 5
    ;;
  *)
    exit 1
    ;;
esac
