#!/usr/bin/env bash

# Summary reporting helpers. Designed to be sourced by interactive shells and
# non-interactive scripts alike. The summary:: API collects events in memory and
# pretty-prints them when the process exits.

if [ -n "${SUGARKUBE_SUMMARY_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
SUGARKUBE_SUMMARY_LOADED=1

SUMMARY__INITIALIZED=${SUMMARY__INITIALIZED:-0}
SUMMARY__EMITTED=${SUMMARY__EMITTED:-0}
SUMMARY__TRAP_SET=${SUMMARY__TRAP_SET:-0}
SUMMARY__CURRENT_SECTION=${SUMMARY__CURRENT_SECTION:-}
SUMMARY__ENTRIES=()

SUMMARY__SYMBOL_OK="✅"
SUMMARY__SYMBOL_WARN="⚠️"
SUMMARY__SYMBOL_FAIL="❌"
SUMMARY__SYMBOL_SKIP="⏭️"

summary_enabled() {
  [ "${SUGARKUBE_SUMMARY_SUPPRESS:-0}" != "1" ]
}

summary__with_strict() {
  # Execute command directly without wrapper
  # Callers (k3s-discover.sh, tests) already set -euo pipefail
  # Avoiding subshells prevents kcov instrumentation depth issues
  "$@"
}

summary__now_impl() {
  python3 - <<'PY' 2>/dev/null || date +%s%3N
import time
print(int(time.time() * 1000))
PY
}

summary_now_ms() {
  summary__with_strict summary__now_impl
}

summary_elapsed_ms() {
  local start_ms="$1"
  local now
  now="$(summary_now_ms)"
  case "${start_ms}" in
    ''|*[!0-9-]*) start_ms=0 ;;
  esac
  case "${now}" in
    ''|*[!0-9-]*) now=0 ;;
  esac
  if [ "${now}" -lt "${start_ms}" ]; then
    now="${start_ms}"
  fi
  printf '%d\n' $((now - start_ms))
}

summary__sanitize() {
  local value="$*"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  printf '%s' "${value}"
}

summary__append_entry() {
  local type="$1"
  shift || true
  local entry="${type}"
  local part
  for part in "$@"; do
    entry+=$'\t'
    entry+="${part}"
  done
  SUMMARY__ENTRIES+=("${entry}")
}

summary__setup_colors_impl() {
  SUMMARY_IS_TTY=0
  SUMMARY_COLOR_RESET=""
  SUMMARY_COLOR_STRONG=""
  SUMMARY_COLOR_OK=""
  SUMMARY_COLOR_WARN=""
  SUMMARY_COLOR_FAIL=""
  SUMMARY_COLOR_SKIP=""

  if [ -t 1 ] && [ "${TERM:-}" != "dumb" ]; then
    SUMMARY_IS_TTY=1
  fi
  if [ "${SUMMARY_FORCE_TTY:-0}" = "1" ]; then
    SUMMARY_IS_TTY=1
  fi
  if [ "${SUMMARY_IS_TTY}" -ne 1 ]; then
    return 0
  fi
  if ! command -v tput >/dev/null 2>&1; then
    SUMMARY_IS_TTY=0
    return 0
  fi
  local colors
  if ! colors="$(tput colors 2>/dev/null)"; then
    SUMMARY_IS_TTY=0
    return 0
  fi
  case "${colors}" in
    ''|*[!0-9]*) SUMMARY_IS_TTY=0 ;;
    0) SUMMARY_IS_TTY=0 ;;
  esac
  if [ "${SUMMARY_IS_TTY}" -ne 1 ]; then
    return 0
  fi
  SUMMARY_COLOR_RESET="$(tput sgr0 2>/dev/null || printf '')"
  SUMMARY_COLOR_STRONG="$(tput bold 2>/dev/null || printf '')"
  SUMMARY_COLOR_OK="$(tput setaf 2 2>/dev/null || printf '')"
  SUMMARY_COLOR_WARN="$(tput setaf 3 2>/dev/null || printf '')"
  SUMMARY_COLOR_FAIL="$(tput setaf 1 2>/dev/null || printf '')"
  SUMMARY_COLOR_SKIP="$(tput setaf 4 2>/dev/null || printf '')"
}

summary__setup_colors() {
  summary__setup_colors_impl
}

summary__register_exit_trap_impl() {
  trap 'summary::emit' EXIT
}

summary__register_exit_trap() {
  if [ "${SUMMARY__TRAP_SET}" -ne 1 ]; then
    summary__with_strict summary__register_exit_trap_impl
    SUMMARY__TRAP_SET=1
  fi
}

summary__ensure_init() {
  if [ "${SUMMARY__INITIALIZED}" -ne 1 ]; then
    summary::init
  fi
}

summary::init() {
  if ! summary_enabled; then
    SUMMARY__INITIALIZED=0
    SUMMARY__EMITTED=0
    return 0
  fi
  if [ "${SUMMARY__INITIALIZED}" -eq 1 ]; then
    return 0
  fi
  SUMMARY__INITIALIZED=1
  SUMMARY__EMITTED=0
  SUMMARY__CURRENT_SECTION=""
  SUMMARY__ENTRIES=()
  summary__setup_colors
  summary__register_exit_trap
}

summary::section() {
  summary__ensure_init
  if ! summary_enabled; then
    return 0
  fi
  local title
  title="$(summary__sanitize "$*")"
  SUMMARY__CURRENT_SECTION="${title}"
  summary__append_entry "section" "${SUMMARY__CURRENT_SECTION}"
}

summary__normalise_status() {
  local raw="${1:-}"
  case "${raw}" in
    ok|Ok|oK|OK) printf 'OK' ;;
    warn|Warn|WARN) printf 'WARN' ;;
    fail|Fail|FAIL) printf 'FAIL' ;;
    skip|Skip|SKIP) printf 'SKIP' ;;
    *) printf '%s' "$(printf '%s' "${raw}" | tr '[:lower:]' '[:upper:]')" ;;
  esac
}

summary::step() {
  summary__ensure_init
  if ! summary_enabled; then
    return 0
  fi
  if [ "$#" -lt 2 ]; then
    return 0
  fi
  local status label detail
  status="$(summary__normalise_status "$1")"
  shift
  label="$(summary__sanitize "$1")"
  shift
  if [ "$#" -gt 0 ]; then
    detail="$(summary__sanitize "$*")"
  else
    detail=""
  fi
  summary__append_entry "step" "${SUMMARY__CURRENT_SECTION}" "${status}" "${label}" "${detail}"
}

summary::kv() {
  summary__ensure_init
  if ! summary_enabled; then
    return 0
  fi
  if [ "$#" -lt 1 ]; then
    return 0
  fi
  local key value
  key="$(summary__sanitize "$1")"
  shift
  if [ "$#" -gt 0 ]; then
    value="$(summary__sanitize "$*")"
  else
    value=""
  fi
  summary__append_entry "kv" "${SUMMARY__CURRENT_SECTION}" "${key}" "${value}"
}

summary__format_step() {
  local status="$1"
  local label="$2"
  local detail="$3"
  local color=""
  local symbol=""
  case "${status}" in
    OK)
      symbol="${SUMMARY__SYMBOL_OK}"
      color="${SUMMARY_COLOR_OK}"
      ;;
    WARN)
      symbol="${SUMMARY__SYMBOL_WARN}"
      color="${SUMMARY_COLOR_WARN}"
      ;;
    FAIL)
      symbol="${SUMMARY__SYMBOL_FAIL}"
      color="${SUMMARY_COLOR_FAIL}"
      ;;
    SKIP)
      symbol="${SUMMARY__SYMBOL_SKIP}"
      color="${SUMMARY_COLOR_SKIP}"
      ;;
    *)
      symbol="${status}"
      color=""
      ;;
  esac
  local reset=""
  if [ -n "${color}" ] && [ -n "${SUMMARY_COLOR_RESET}" ]; then
    reset="${SUMMARY_COLOR_RESET}"
  fi
  local text
  text="${symbol} ${label}"
  if [ -n "${detail}" ]; then
    text+=" — ${detail}"
  fi
  if [ -n "${color}" ] && [ -n "${reset}" ]; then
    printf '%s%s%s' "${color}" "${text}" "${reset}"
  else
    printf '%s' "${text}"
  fi
}

summary__format_kv() {
  local key="$1"
  local value="$2"
  local strong=""
  local reset=""
  if [ -n "${SUMMARY_COLOR_STRONG}" ] && [ -n "${SUMMARY_COLOR_RESET}" ]; then
    strong="${SUMMARY_COLOR_STRONG}"
    reset="${SUMMARY_COLOR_RESET}"
  fi
  if [ -n "${strong}" ]; then
    printf '%s%s:%s %s' "${strong}" "${key}" "${reset}" "${value}"
  else
    printf '%s: %s' "${key}" "${value}"
  fi
}

summary__ensure_summary_file_impl() {
  local file="$1"
  if [ -z "${file}" ]; then
    return 0
  fi
  local dir
  dir="$(dirname "${file}")"
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}"
  fi
  if [ ! -f "${file}" ]; then
    : >"${file}"
  fi
}

summary__ensure_summary_file() {
  summary__with_strict summary__ensure_summary_file_impl "$@"
}

summary__write_output_impl() {
  local output="$1"
  if [ -z "${output}" ]; then
    return 0
  fi
  printf '%s' "${output}" >&2
}

summary__write_output() {
  summary__with_strict summary__write_output_impl "$@"
}

summary__tee_output_impl() {
  local output="$1"
  local file="$2"
  if [ -z "${file}" ]; then
    return 0
  fi
  summary__ensure_summary_file "${file}"
  printf '%s' "${output}" | tee -a "${file}" >/dev/null
}

summary__tee_output() {
  summary__with_strict summary__tee_output_impl "$@"
}

summary__emit_impl() {
  if [ "${SUMMARY__INITIALIZED}" -ne 1 ]; then
    return 0
  fi
  if [ "${SUMMARY__EMITTED}" -eq 1 ]; then
    return 0
  fi
  SUMMARY__EMITTED=1
  if ! summary_enabled; then
    return 0
  fi
  local -a lines=()
  lines+=("Summary:")
  local printed_any=0
  local current_section=""
  local last_section=""
  local section_pending=0
  local entry type field1 field2 field3 field4
  for entry in "${SUMMARY__ENTRIES[@]}"; do
    IFS=$'\t' read -r type field1 field2 field3 field4 <<<"${entry}"
    case "${type}" in
      section)
        current_section="${field1}"
        section_pending=1
        ;;
      step)
        printed_any=1
        if [ "${section_pending}" -eq 1 ] || [ "${current_section}" != "${last_section}" ]; then
          section_pending=0
          if [ -n "${current_section}" ]; then
            lines+=("")
            if [ -n "${SUMMARY_COLOR_STRONG}" ] && [ -n "${SUMMARY_COLOR_RESET}" ]; then
              lines+=("  ${SUMMARY_COLOR_STRONG}${current_section}${SUMMARY_COLOR_RESET}")
            else
              lines+=("  ${current_section}")
            fi
          elif [ -n "${last_section}" ]; then
            lines+=("")
          elif [ "${#lines[@]}" -eq 1 ]; then
            lines+=("")
          fi
          last_section="${current_section}"
        fi
        local indent
        if [ -n "${current_section}" ]; then
          indent="    "
        else
          indent="  "
        fi
        lines+=("${indent}$(summary__format_step "${field2}" "${field3}" "${field4}")")
        ;;
      kv)
        printed_any=1
        if [ "${section_pending}" -eq 1 ] || [ "${current_section}" != "${last_section}" ]; then
          section_pending=0
          if [ -n "${current_section}" ]; then
            lines+=("")
            if [ -n "${SUMMARY_COLOR_STRONG}" ] && [ -n "${SUMMARY_COLOR_RESET}" ]; then
              lines+=("  ${SUMMARY_COLOR_STRONG}${current_section}${SUMMARY_COLOR_RESET}")
            else
              lines+=("  ${current_section}")
            fi
          elif [ -n "${last_section}" ]; then
            lines+=("")
          elif [ "${#lines[@]}" -eq 1 ]; then
            lines+=("")
          fi
          last_section="${current_section}"
        fi
        local indent
        if [ -n "${current_section}" ]; then
          indent="    "
        else
          indent="  "
        fi
        lines+=("${indent}$(summary__format_kv "${field2}" "${field3}")")
        ;;
    esac
  done
  if [ "${printed_any}" -eq 0 ]; then
    lines+=("  (no entries)")
  fi
  local output=""
  printf -v output '%s\n' "${lines[@]}"
  summary__write_output "${output}"
  if [ -n "${SUGARKUBE_SUMMARY_FILE:-}" ]; then
    summary__tee_output "${output}" "${SUGARKUBE_SUMMARY_FILE}"
  fi
}

summary::emit() {
  summary__emit_impl || true
}

summary_skip() {
  if [ "$#" -lt 1 ]; then
    return 0
  fi
  local label="$1"
  local note="${2:-}"
  summary::step SKIP "${label}" "${note}"
}

summary_run() {
  local note=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --note)
        shift
        note="${1:-}"
        shift || true
        ;;
      --)
        shift
        break
        ;;
      --*)
        break
        ;;
      *)
        break
        ;;
    esac
  done

  if [ "$#" -lt 1 ]; then
    return 0
  fi

  local label="$1"
  shift
  local start_ms
  start_ms="$(summary_now_ms)"

  set +e
  "$@"
  local exit_code=$?
  set -e

  local duration_ms
  duration_ms="$(summary_elapsed_ms "${start_ms}")"
  local status="OK"
  if [ "${exit_code}" -ne 0 ]; then
    status="FAIL"
  fi

  local detail="elapsed_ms=${duration_ms}"
  if [ -n "${note}" ]; then
    detail="${note} ${detail}"
  fi

  summary::step "${status}" "${label}" "${detail}"
  return "${exit_code}"
}

summary_finalize() {
  summary::emit
}
