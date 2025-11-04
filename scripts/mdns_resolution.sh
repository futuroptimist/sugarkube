#!/usr/bin/env bash
# mdns_resolution.sh - mDNS resolution functions (NSS, CLI, DBus)
# shellcheck disable=SC3040,SC3041,SC3043

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

  # shellcheck disable=SC2034  # Used externally by sourcing scripts
  MDNS_LAST_CMD_PARSED_IPV4="${ipv4}"

  if [ -n "${expected_ipv4}" ] && [ "${ipv4}" != "${expected_ipv4}" ]; then
    printf '%s' "${ipv4}"
    return 2
  fi

  printf '%s' "${ipv4}"
  return 0
}

resolve_srv_target_cli() {
  local target="$1"
  local expected_ipv4="$2"

  if [ -z "${target}" ] || [ -z "${expected_ipv4}" ]; then
    return 3
  fi

  # Try NSS first (getent hosts)
  local nss_result
  if nss_result="$(mdns_check_nss_host "${target}" "${expected_ipv4}" 2>/dev/null)"; then
    printf '%s' "${nss_result}"
    return 0
  fi
  local nss_rc=$?

  # If NSS failed with mismatch, return that
  if [ "${nss_rc}" -eq 2 ]; then
    return 2
  fi

  # NSS failed, try avahi-resolve-host-name as fallback
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
  SELF_RESOLVE_REASON=""

  local host="${SELF_LOCAL_HOST:-}"
  if [ -z "${host}" ]; then
    SELF_RESOLVE_REASON="no_local_host"
    self_resolve_log "${stage}" "${attempt}"
    return 3
  fi

  local ipv4
  if ipv4="$(resolve_self_ipv4 "${host}" "${EXPECTED_IPV4}" 2>/dev/null)"; then
    SELF_RESOLVE_STATUS=0
    SELF_RESOLVE_HOST="${host}"
    SELF_RESOLVE_IPV4="${ipv4}"
    SELF_RESOLVE_COMMAND="${MDNS_LAST_CMD_DISPLAY:-}"
    SELF_RESOLVE_DURATION="${MDNS_LAST_CMD_DURATION_MS:-}"
  else
    SELF_RESOLVE_STATUS=$?
    SELF_RESOLVE_HOST="${host}"
    SELF_RESOLVE_IPV4="${ipv4}"
    SELF_RESOLVE_COMMAND="${MDNS_LAST_CMD_DISPLAY:-}"
    SELF_RESOLVE_DURATION="${MDNS_LAST_CMD_DURATION_MS:-}"
    case "${SELF_RESOLVE_STATUS}" in
      1)
        SELF_RESOLVE_REASON="resolve_failed"
        ;;
      2)
        SELF_RESOLVE_REASON="ipv4_mismatch"
        ;;
      3)
        SELF_RESOLVE_REASON="tool_missing"
        ;;
      *)
        SELF_RESOLVE_REASON="unknown_error"
        ;;
    esac
  fi

  self_resolve_log "${stage}" "${attempt}"
  return "${SELF_RESOLVE_STATUS}"
}

self_resolve_handle_success() {
  local attempt="$1"
  local stage="$2"

  local host="${SELF_RESOLVE_HOST:-}"
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
  # shellcheck disable=SC2154  # script_start_ms is defined in sourcing script
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
