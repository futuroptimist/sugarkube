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
  [ "$(log__level_to_num "$1" 2>/dev/null || echo 1)" -le \
    "$(log__level_to_num "${LOG_LEVEL}" 2>/dev/null || echo 1)" ]
}

log__timestamp() {
  date -Is 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z'
}

log_kv() {
  log__level="${1:-info}"
  if [ "$#" -lt 2 ]; then
    return 0
  fi
  log__event="$2"
  shift 2

  if ! log__should_emit "${log__level}"; then
    unset log__level log__event
    return 0
  fi

  log__message="ts=$(log__timestamp) level=${log__level} event=${log__event}"
  for log__kv in "$@"; do
    [ -n "${log__kv}" ] || continue
    log__message="${log__message} ${log__kv}"
  done
  printf '%s\n' "${log__message}"
  unset log__level log__event log__message log__kv
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

