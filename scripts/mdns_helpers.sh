#!/usr/bin/env bash
# mdns_helpers.sh - Utility functions for mDNS operations
# shellcheck disable=SC3040,SC3041,SC3043

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
  # shellcheck disable=SC2034  # Used externally by sourcing scripts
  MDNS_LAST_CMD_DISPLAY="${cmd_display}"
  # shellcheck disable=SC2034  # Used externally by sourcing scripts
  MDNS_LAST_CMD_DURATION_MS="${duration_ms}"
  # shellcheck disable=SC2034  # Used externally by sourcing scripts
  MDNS_LAST_CMD_OUTPUT="${output}"
  # shellcheck disable=SC2034  # Used externally by sourcing scripts
  MDNS_LAST_CMD_RC="${rc}"
  # shellcheck disable=SC2034  # Used externally by sourcing scripts
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

extract_wait_field() {
  local field_name="$1"
  if [ -z "${field_name}" ]; then
    return 1
  fi
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

host_matches_self() {
  local test_host="$1"
  if [ -z "${test_host}" ]; then
    return 1
  fi
  if [ "${HOSTNAME_CHECK_ENABLED:-0}" -ne 1 ]; then
    return 0
  fi
  local test_normalized
  test_normalized="$(printf '%s' "${test_host}" | tr '[:upper:]' '[:lower:]' | sed 's/\.$//')"
  local old_ifs="${IFS}"
  IFS=$'\n'
  for alias in ${SELF_HOSTNAME_ALIASES}; do
    if [ "${test_normalized}" = "${alias}" ]; then
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

compute_delay_ms() {
  python3 - "$@" <<'PY'
import random
import sys

def compute_delay(attempt, start, cap, jitter):
    if attempt <= 0:
        return 0
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
    return delay

try:
    attempt = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    cap = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
    jitter = float(sys.argv[4]) if len(sys.argv) > 4 else 0.2
except (ValueError, IndexError):
    print(0)
    sys.exit(0)

delay = compute_delay(attempt, start, cap, jitter)
print(delay)
PY
}
