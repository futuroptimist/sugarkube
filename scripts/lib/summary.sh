#!/usr/bin/env bash

# Lightweight summary helpers. Provides a small stable API that scripts can call
# to record human-friendly results. The output is colourised when stdout is a TTY
# (and TERM is not "dumb"), and falls back to plain text otherwise.

if [ -n "${SUGARKUBE_SUMMARY_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
export SUGARKUBE_SUMMARY_LOADED=1

# shellcheck disable=SC2034  # referenced from other files
SUMMARY_IS_TTY=0
SUMMARY__ENABLED=0
SUMMARY__EMITTED=0
SUMMARY__EXIT_TRAP_SET=0
SUMMARY__ENTRIES=()
SUMMARY__KV_ENTRIES=()
SUMMARY__LAST_ENTRY_INDEX=-1
SUMMARY__HAS_DATA=0

SUMMARY__FMT_RESET=""
SUMMARY__FMT_BOLD=""
SUMMARY__FMT_OK=""
SUMMARY__FMT_WARN=""
SUMMARY__FMT_FAIL=""
SUMMARY__FMT_SKIP=""

SUMMARY__SYMBOL_OK="✅"
SUMMARY__SYMBOL_WARN="⚠️"
SUMMARY__SYMBOL_FAIL="❌"
SUMMARY__SYMBOL_SKIP="⏭️"

summary__with_strict() {
  local __restore
  __restore="$(set +o)"
  set -Eeuo pipefail
  "$@"
  local __status=$?
  eval "${__restore}"
  return "${__status}"
}

summary__sanitize() {
  local value="$*"
  value="${value//$'\r'/ }"
  value="${value//$'\n'/ }"
  value="${value//$'\t'/ }"
  printf '%s' "${value}"
}

summary__is_status() {
  case "$1" in
    OK|ok|Ok|oK|WARN|warn|Warn|FAIL|fail|Fail|SKIP|skip|Skip)
      return 0
      ;;
  esac
  return 1
}

summary__normalise_status() {
  case "$1" in
    ok|Ok|oK) printf 'OK' ;;
    warn|Warn) printf 'WARN' ;;
    fail|Fail) printf 'FAIL' ;;
    skip|Skip) printf 'SKIP' ;;
    OK|WARN|FAIL|SKIP) printf '%s' "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}

summary__status_symbol() {
  case "$1" in
    OK) printf '%s' "${SUMMARY__SYMBOL_OK}" ;;
    WARN) printf '%s' "${SUMMARY__SYMBOL_WARN}" ;;
    FAIL) printf '%s' "${SUMMARY__SYMBOL_FAIL}" ;;
    SKIP) printf '%s' "${SUMMARY__SYMBOL_SKIP}" ;;
    *) printf '%s' "$1" ;;
  esac
}

summary__status_colour() {
  case "$1" in
    OK) printf '%s' "${SUMMARY__FMT_OK}" ;;
    WARN) printf '%s' "${SUMMARY__FMT_WARN}" ;;
    FAIL) printf '%s' "${SUMMARY__FMT_FAIL}" ;;
    SKIP) printf '%s' "${SUMMARY__FMT_SKIP}" ;;
    *) printf '' ;;
  esac
}

summary_enabled() {
  [ "${SUMMARY__ENABLED:-0}" -eq 1 ]
}

summary_now_ms_impl() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
    return 0
  fi
  date +%s%3N
}

summary_now_ms() {
  local __restore __output __status
  __restore="$(set +o)"
  set -Eeuo pipefail
  __output="$(summary_now_ms_impl)"
  __status=$?
  eval "${__restore}"
  printf '%s\n' "${__output}"
  return "${__status}"
}

summary_elapsed_ms() {
  local start_ms="$1"
  local __restore __status now
  __restore="$(set +o)"
  set -Eeuo pipefail
  now="$(summary_now_ms_impl)"
  __status=$?
  eval "${__restore}"
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
  return "${__status}"
}

summary__append_entry() {
  SUMMARY__ENTRIES+=("$1")
  SUMMARY__LAST_ENTRY_INDEX=${#SUMMARY__ENTRIES[@]}
  SUMMARY__HAS_DATA=1
}

summary__append_kv() {
  SUMMARY__KV_ENTRIES+=("$1")
  SUMMARY__HAS_DATA=1
}

summary__format_duration() {
  local duration="$1"
  if [ -z "${duration}" ]; then
    printf ''
    return 0
  fi
  printf '%s ms' "${duration}"
}

summary__init_impl() {
  if [ "${SUMMARY__ENABLED}" -eq 1 ]; then
    return 0
  fi

  SUMMARY__ENABLED=1
  SUMMARY__EMITTED=0
  SUMMARY__ENTRIES=()
  SUMMARY__KV_ENTRIES=()
  SUMMARY__LAST_ENTRY_INDEX=-1

  SUMMARY_IS_TTY=0
  if [ -t 1 ] && [ "${TERM:-}" != 'dumb' ]; then
    SUMMARY_IS_TTY=1
  fi

  SUMMARY__FMT_RESET=""
  SUMMARY__FMT_BOLD=""
  SUMMARY__FMT_OK=""
  SUMMARY__FMT_WARN=""
  SUMMARY__FMT_FAIL=""
  SUMMARY__FMT_SKIP=""

  if [ "${SUMMARY_IS_TTY}" -eq 1 ] && command -v tput >/dev/null 2>&1; then
    local reset bold colours colour_count
    if reset="$(tput sgr0 2>/dev/null)"; then
      SUMMARY__FMT_RESET="${reset}"
    fi
    if bold="$(tput bold 2>/dev/null)"; then
      SUMMARY__FMT_BOLD="${bold}"
    fi
    if colours="$(tput colors 2>/dev/null)"; then
      colour_count="${colours}"
    else
      colour_count=0
    fi
    if [ "${colour_count}" -ge 8 ]; then
      SUMMARY__FMT_OK="$(tput setaf 2 2>/dev/null || printf '')"
      SUMMARY__FMT_WARN="$(tput setaf 3 2>/dev/null || printf '')"
      SUMMARY__FMT_FAIL="$(tput setaf 1 2>/dev/null || printf '')"
      SUMMARY__FMT_SKIP="$(tput setaf 4 2>/dev/null || printf '')"
    fi
  fi

  if [ "${SUMMARY__EXIT_TRAP_SET}" -eq 0 ]; then
    trap 'summary::emit || true' EXIT
    SUMMARY__EXIT_TRAP_SET=1
  fi
}

summary::init() {
  summary__with_strict summary__init_impl "$@"
}

summary__section_impl() {
  local title
  title="$(summary__sanitize "$*")"
  SUMMARY__CURRENT_SECTION="${title}"
  summary__append_entry "section\t${title}"
}

summary::section() {
  summary__section_impl "$@"
}

summary__step_impl() {
  if [ $# -lt 1 ]; then
    return 0
  fi

  local status label duration note

  if summary__is_status "$1"; then
    status="$(summary__normalise_status "$1")"
    shift
    label="$(summary__sanitize "$1")"
    shift || true
  else
    label="$(summary__sanitize "$1")"
    shift
    status="$(summary__normalise_status "${1:-OK}")"
    shift || true
  fi

  duration=""
  note=""
  if [ $# -gt 0 ]; then
    case "$1" in
      ''|*[!0-9-]*) ;;
      *)
        duration="$1"
        shift
        ;;
    esac
  fi
  if [ $# -gt 0 ]; then
    note="$(summary__sanitize "$1")"
  fi

  summary__append_entry "step\t${status}\t${label}\t${duration}\t${note}"
}

summary::step() {
  summary__step_impl "$@"
}

summary__kv_impl() {
  if [ $# -lt 1 ]; then
    return 0
  fi
  local key value
  key="$(summary__sanitize "$1")"
  value=""
  if [ $# -gt 1 ]; then
    shift
    value="$(summary__sanitize "$*")"
  fi
  summary__append_kv "kv\t${key}\t${value}"
}

summary::kv() {
  summary__kv_impl "$@"
}

summary__emit_impl() {
  if [ "${SUMMARY__EMITTED}" -eq 1 ]; then
    return 0
  fi
  SUMMARY__EMITTED=1

  local -a lines=()
  local title="Summary"
  if [ -n "${SUMMARY__FMT_BOLD}" ] && [ -n "${SUMMARY__FMT_RESET}" ]; then
    lines+=("${SUMMARY__FMT_BOLD}${title}${SUMMARY__FMT_RESET}")
  else
    lines+=("${title}")
  fi
  lines+=("${title//?/-}")

  local entry kind status label duration note colour symbol details key value
  for entry in "${SUMMARY__ENTRIES[@]}"; do
    IFS=$'\t' read -r kind status label duration note <<<"${entry}"
    case "${kind}" in
      section)
        lines+=("")
        if [ -n "${SUMMARY__FMT_BOLD}" ] && [ -n "${SUMMARY__FMT_RESET}" ]; then
          lines+=("${SUMMARY__FMT_BOLD}${label}${SUMMARY__FMT_RESET}")
        else
          lines+=("${label}")
        fi
        ;;
      step)
        colour="$(summary__status_colour "${status}")"
        symbol="$(summary__status_symbol "${status}")"
        if [ -n "${colour}" ] && [ -n "${SUMMARY__FMT_RESET}" ]; then
          symbol="${colour}${symbol}${SUMMARY__FMT_RESET}"
        fi
        if [ -n "${SUMMARY__FMT_BOLD}" ] && [ -n "${SUMMARY__FMT_RESET}" ]; then
          label="${SUMMARY__FMT_BOLD}${label}${SUMMARY__FMT_RESET}"
        fi
        details=""
        if [ -n "${duration}" ]; then
          details="$(summary__format_duration "${duration}")"
        fi
        if [ -n "${note}" ]; then
          if [ -n "${details}" ]; then
            details="${details}; ${note}"
          else
            details="${note}"
          fi
        fi
        if [ -n "${details}" ]; then
          lines+=("  ${symbol} ${label} (${details})")
        else
          lines+=("  ${symbol} ${label}")
        fi
        ;;
    esac
  done

  for entry in "${SUMMARY__KV_ENTRIES[@]}"; do
    IFS=$'\t' read -r kind key value <<<"${entry}"
    if [ "${kind}" = 'kv' ]; then
      if [ -n "${value}" ]; then
        lines+=("    ${key}: ${value}")
      else
        lines+=("    ${key}")
      fi
    fi
  done

  if [ "${#SUMMARY__ENTRIES[@]}" -eq 0 ] && [ "${#SUMMARY__KV_ENTRIES[@]}" -eq 0 ]; then
    lines+=("(no summary entries recorded)")
  fi

  local output=""
  for entry in "${lines[@]}"; do
    output+="${entry}"$'\n'
  done

  if [ -n "${SUGARKUBE_SUMMARY_FILE:-}" ]; then
    local summary_dir
    summary_dir="$(dirname "${SUGARKUBE_SUMMARY_FILE}")"
    mkdir -p "${summary_dir}" 2>/dev/null || true
    printf '%s' "${output}" | tee "${SUGARKUBE_SUMMARY_FILE}" >/dev/null
  fi

  printf '%s' "${output}"
}

summary::emit() {
  summary__with_strict summary__emit_impl "$@"
}

summary_skip() {
  local label="$1"
  local note="${2:-}"
  if summary_enabled; then
    if [ -n "${note}" ]; then
      summary::step SKIP "${label}" "${note}"
    else
      summary::step SKIP "${label}"
    fi
  fi
}

summary_run() {
  if [ $# -lt 1 ]; then
    return 0
  fi
  local label="$1"
  shift || true
  if ! summary_enabled; then
    "$@"
    return "$?"
  fi
  local summary_start status restore_errexit
  summary_start="$(summary_now_ms)"
  restore_errexit=0
  case "$-" in
    *e*) restore_errexit=1 ;;
  esac
  set +e
  "$@"
  status=$?
  if [ "${restore_errexit}" -eq 1 ]; then
    set -e
  else
    set +e
  fi
  if [ "${status}" -eq 0 ]; then
    summary::step OK "${label}" "$(summary_elapsed_ms "${summary_start}")"
  else
    summary::step FAIL "${label}" "$(summary_elapsed_ms "${summary_start}")" "exit=${status}"
  fi
  return "${status}"
}

summary_finalize() {
  summary::emit
}
