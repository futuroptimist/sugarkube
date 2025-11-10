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

# Source modular mDNS components
# shellcheck source=scripts/mdns_helpers.sh
. "${SCRIPT_DIR}/mdns_helpers.sh"
# shellcheck source=scripts/mdns_resolution.sh
. "${SCRIPT_DIR}/mdns_resolution.sh"
# shellcheck source=scripts/mdns_type_check.sh
. "${SCRIPT_DIR}/mdns_type_check.sh"

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

MDNS_LAST_CMD_DISPLAY=""
MDNS_LAST_CMD_DURATION_MS=""
# shellcheck disable=SC2034  # Set by run_command_capture in mdns_helpers.sh
MDNS_LAST_CMD_OUTPUT=""
MDNS_LAST_CMD_RC=""
# shellcheck disable=SC2034  # Set by resolve functions in mdns_resolution.sh
MDNS_LAST_CMD_PARSED_IPV4=""
MDNS_LAST_FAILURE_COMMAND=""
MDNS_LAST_FAILURE_DURATION=""
DBUS_SCRIPT_PATH="${SCRIPT_DIR}/mdns_selfcheck_dbus.sh"
DBUS_CLI_FALLBACK_ENABLED=0
DBUS_CLI_FALLBACK_DISABLED=0
DBUS_CLI_FALLBACK_ATTEMPTS=0

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
INITIAL_BROWSE_ATTEMPTS=0

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
  IFS=$'\n'
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

ensure_systemd_unit_active() {
  local unit="$1"
  if [ -z "${unit}" ]; then
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    log_debug mdns_systemd outcome=skip reason=systemctl_missing unit="${unit}"
    return 0
  fi
  if systemctl is-active --quiet "${unit}"; then
    log_debug mdns_systemd outcome=ok state=active unit="${unit}"
    return 0
  fi

  local start_cmd=(systemctl start "${unit}")
  if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      start_cmd=(sudo "${start_cmd[@]}")
    else
      log_info mdns_systemd outcome=skip reason=sudo_missing unit="${unit}" severity=warn
      return 1
    fi
  fi

  if "${start_cmd[@]}" >/dev/null 2>&1; then
    log_info mdns_systemd outcome=started unit="${unit}" severity=info
    return 0
  fi

  local rc=$?
  log_info mdns_systemd outcome=error unit="${unit}" status="${rc}" severity=warn
  return "${rc}"
}


ensure_avahi_systemd_units() {
  ensure_systemd_unit_active dbus || true
  ensure_systemd_unit_active avahi-daemon || true
}


mdns_liveness_probe() {
  local host="${SELF_LOCAL_HOST:-}"
  local signal="liveness"
  local dbus_allowed=1

  case "${dbus_mode:-auto}" in
    0|false|False|FALSE|no|No|NO|off|Off|OFF)
      dbus_allowed=0
      ;;
  esac

  if [ "${dbus_allowed}" -eq 1 ]; then
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
  else
    log_debug mdns_liveness outcome=skip signal=dbus_hostname reason=dbus_disabled
  fi

  if [ -n "${host}" ] && [ -n "${EXPECTED_IPV4}" ]; then
    self_resolve_attempt "${signal}" 0 >/dev/null 2>&1 || true
  else
    log_debug mdns_liveness outcome=skip signal=self_resolve reason=missing_context
  fi
}

mdns_cli_dbus_fallback() {
  local cli_rc="$1"
  local attempt_num="$2"

  if [ "${DBUS_CLI_FALLBACK_ENABLED}" -ne 1 ]; then
    return 1
  fi
  if [ "${DBUS_CLI_FALLBACK_DISABLED}" -eq 1 ]; then
    return 1
  fi

  DBUS_CLI_FALLBACK_ATTEMPTS=$((DBUS_CLI_FALLBACK_ATTEMPTS + 1))
  log_debug mdns_selfcheck_dbus outcome=retry reason=cli_failure cli_rc="${cli_rc}" attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"

  ensure_avahi_systemd_units || true

  if [ -x "${SCRIPT_DIR}/wait_for_avahi_dbus.sh" ]; then
    local wait_output=""
    local wait_status=0
    if ! wait_output="$("${SCRIPT_DIR}/wait_for_avahi_dbus.sh" 2>&1)"; then
      wait_status=$?
      if [ -n "${wait_output}" ]; then
        printf '%s\n' "${wait_output}"
      fi
      case "${wait_status}" in
        2)
          DBUS_CLI_FALLBACK_DISABLED=1
          log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_wait_disabled attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
          ;;
        0)
          ;;
        *)
          log_debug mdns_selfcheck_dbus outcome=lag reason=dbus_wait_failed status="${wait_status}" attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
          ;;
      esac
    elif [ -n "${wait_output}" ]; then
      printf '%s\n' "${wait_output}"
    fi
    if [ "${DBUS_CLI_FALLBACK_DISABLED}" -eq 1 ]; then
      return 1
    fi
  fi

  local dbus_script="${DBUS_SCRIPT_PATH}"
  if [ ! -x "${dbus_script}" ]; then
    DBUS_CLI_FALLBACK_DISABLED=1
    log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_script_missing attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
    return 1
  fi

  if SUGARKUBE_MDNS_DBUS=1 "${dbus_script}"; then
    log_info mdns_selfcheck outcome=recovered method=dbus attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
    return 0
  fi

  local status=$?
  case "${status}" in
    2)
      DBUS_CLI_FALLBACK_DISABLED=1
      log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_unsupported attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
      ;;
    1)
      log_debug mdns_selfcheck_dbus outcome=retry reason=dbus_attempt_failed status="${status}" attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
      ;;
    *)
      log_debug mdns_selfcheck_dbus outcome=error reason=dbus_attempt_failed status="${status}" attempt="${attempt_num}" fallback_attempt="${DBUS_CLI_FALLBACK_ATTEMPTS}"
      ;;
  esac

  return 1
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

mdns_liveness_probe

mdns_selfcheck__service_type_check

attempt=1
last_reason=""
miss_count=0
while [ "${attempt}" -le "${ATTEMPTS}" ]; do
  # Use parsable semicolon-delimited output with resolution and terminate flags
  MDNS_LAST_FAILURE_COMMAND=""
  MDNS_LAST_FAILURE_DURATION=""
  effective_attempts="${attempt}"
  if [ "${INITIAL_BROWSE_READY}" -eq 1 ]; then
    browse_output="${INITIAL_BROWSE_OUTPUT}"
    browse_command="${active_command:-}"
    browse_duration="${active_duration:-}"
    if [ "${INITIAL_BROWSE_ATTEMPTS}" -gt 0 ]; then
      effective_attempts="${INITIAL_BROWSE_ATTEMPTS}"
    fi
    INITIAL_BROWSE_READY=0
  else
    # When SUGARKUBE_MDNS_DBUS=1, prefer dbus method and fall back to CLI on failure
    if [ "${SUGARKUBE_MDNS_DBUS:-0}" -eq 1 ] && [ -x "${SCRIPT_DIR}/mdns_selfcheck_dbus.sh" ]; then
      if SUGARKUBE_MDNS_DBUS=1 "${SCRIPT_DIR}/mdns_selfcheck_dbus.sh"; then
        # DBus mode succeeded - emit status and exit with success
        mdns_resolution_status_emit ok attempt="${attempt}" host="${EXPECTED_HOST}" resolve_method="dbus"
        exit 0
      fi
      # DBus failed, log fallback and continue with CLI
      log_info mdns_selfcheck event=dbus_fallback fallback=cli reason=dbus_browse_failed attempt="${attempt}"
    fi

    # Use CLI method (avahi-browse) - either as primary or fallback
    browse_output="$(run_command_capture mdns_browse avahi-browse --parsable --resolve --terminate "${SERVICE_TYPE}" || true)"
    browse_command="${MDNS_LAST_CMD_DISPLAY:-}"
    browse_duration="${MDNS_LAST_CMD_DURATION_MS:-}"
  fi
  browse_rc="${MDNS_LAST_CMD_RC:-0}"
  browse_error=0
  if [ "${INITIAL_BROWSE_READY}" -eq 0 ]; then
    case "${browse_rc}" in
      ''|*[!0-9-]*) browse_rc=0 ;;
    esac
    if [ "${browse_rc}" -ne 0 ]; then
      browse_error=1
      if mdns_cli_dbus_fallback "${browse_rc}" "${attempt}"; then
        exit 0
      fi
    fi
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
          set +e
          resolved="$(resolve_host "${srv_host}")"
          status=$?
          set -e
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
            mdns_resolution_status_emit ok attempt="${effective_attempts}" host="${srv_host}" resolve_method="${resolution_method}"
            log_info mdns_selfcheck outcome=ok host="${srv_host}" ipv4="${resolved_ipv4}" port="${srv_port}" attempts="${effective_attempts}" ms_elapsed="${elapsed_ms}" resolve_method="${resolution_method}"
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
    if [ "${browse_error}" -eq 1 ]; then
      browse_reason="browse_error"
    elif [ -z "${browse_output}" ]; then
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
        # When browse is empty or has errors, prioritize that reason over resolution failures
        if [ "${browse_reason}" = "browse_empty" ] || [ "${browse_reason}" = "browse_error" ]; then
          last_reason="${browse_reason}"
        elif [ "${browse_reason}" = "instance_not_found" ]; then
          # Prioritize instance_not_found when browse had output but no matching instances
          last_reason="${browse_reason}"
        elif [ -n "${SELF_RESOLVE_REASON}" ] && [ "${SELF_RESOLVE_STATUS}" -ne 3 ]; then
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
if [ "${MDNS_RESOLUTION_STATUS_BROWSE}" = "1" ] && [ "${MDNS_RESOLUTION_STATUS_RESOLVE}" = "0" ]; then
  # Browse succeeded but resolution failed (either resolve_failed or ipv4_mismatch)
  # Treat this as a warning since the service was found but couldn't be validated
  if [ "${last_reason}" = "resolve_failed" ] || [ "${last_reason}" = "ipv4_mismatch" ]; then
    warn_kv_args=()
    if [ -n "${MDNS_LAST_FAILURE_COMMAND}" ]; then
      warn_kv_args+=("command=\"$(kv_escape "${MDNS_LAST_FAILURE_COMMAND}")\"")
    fi
    if [ -n "${MDNS_LAST_FAILURE_DURATION}" ]; then
      warn_kv_args+=("command_duration_ms=${MDNS_LAST_FAILURE_DURATION}")
    fi
    mdns_resolution_status_emit warn attempts="${ATTEMPTS}" misses="${miss_count}" ms_elapsed="${elapsed_ms}" host="${EXPECTED_HOST}" reason="${last_reason}" "${warn_kv_args[@]}"
    log_info mdns_selfcheck outcome=warn attempts="${ATTEMPTS}" misses="${miss_count}" reason="${last_reason}" ms_elapsed="${elapsed_ms}" "${warn_kv_args[@]}"
    exit 0
  fi
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
