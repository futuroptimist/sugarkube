#!/usr/bin/env sh
# shellcheck shell=sh

# Shared structured logging helper for shell scripts.
# Provides level-aware logging helpers that emit key=value pairs with
# ISO-8601 timestamps.

: "${LOG_LEVEL:=info}"

log__level_to_num() {
  case "${1}" in
    trace) echo 3 ;;
    debug) echo 2 ;;
    info) echo 1 ;;
    *) echo 1 ;;
  esac
}

log__should_emit() {
  local desired current
  desired="$(log__level_to_num "$1" 2>/dev/null || echo 1)"
  current="$(log__level_to_num "${LOG_LEVEL}" 2>/dev/null || echo 1)"
  [ "${desired}" -le "${current}" ]
}

log__timestamp() {
  date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z'
}

log_kv() {
  local level event
  level="$1"
  shift
  event="$1"
  shift
  if ! log__should_emit "${level}"; then
    return 0
  fi

  local message="ts=$(log__timestamp) level=${level} event=${event}"
  local kv
  for kv in "$@"; do
    [ -n "${kv}" ] || continue
    message="${message} ${kv}"
  done
  printf '%s\n' "${message}"
}

log_info() {
  log_kv info "$@"
}

log_debug() {
  log_kv debug "$@" >&2
}

log_trace() {
  log_kv trace "$@" >&2
}

