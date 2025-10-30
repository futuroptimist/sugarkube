#!/usr/bin/env bash

# Summary reporting helpers used by sugarkube shell recipes. The public API is the
# summary::* namespace which exposes a tiny set of functions that are safe to call
# from both interactive shells and unattended automation.

if [ -n "${SUGARKUBE_SUMMARY_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
SUGARKUBE_SUMMARY_LOADED=1

SUMMARY_DATA=""
SUMMARY_HAS_ITEMS=0
SUMMARY_EMITTED=0
SUMMARY_INITIALIZED=0
SUMMARY_TRAP_SET=0
SUMMARY_IS_TTY=0
SUMMARY_COLOR_RESET=""
SUMMARY_COLOR_SECTION=""
SUMMARY_COLOR_DIM=""
SUMMARY_COLOR_OK=""
SUMMARY_COLOR_WARN=""
SUMMARY_COLOR_FAIL=""
SUMMARY_COLOR_SKIP=""

summary__call_with_safe_opts() {
  local __restore __rc
  __restore="$(set +o)"
  set -Eeuo pipefail
  "$@"
  __rc=$?
  eval "${__restore}"
  return "${__rc}"
}

summary__clean_text() {
  local text="${1:-}"
  text="${text//$'\r'/ }"
  text="${text//$'\n'/ }"
  text="${text//$'\t'/ }"
  text="${text//|/∣}"
  printf '%s' "${text}"
}

summary__append_line() {
  SUMMARY_DATA+="${1}"$'\n'
  SUMMARY_HAS_ITEMS=1
}

summary__status_symbol() {
  case "${1}" in
    OK) printf '✅' ;;
    WARN) printf '⚠️' ;;
    FAIL) printf '❌' ;;
    SKIP) printf '⏭️' ;;
    *) printf '%s' "${1}" ;;
  esac
}

summary__status_color() {
  case "${1}" in
    OK) printf '%s' "${SUMMARY_COLOR_OK}" ;;
    WARN) printf '%s' "${SUMMARY_COLOR_WARN}" ;;
    FAIL) printf '%s' "${SUMMARY_COLOR_FAIL}" ;;
    SKIP) printf '%s' "${SUMMARY_COLOR_SKIP}" ;;
    *) printf '' ;;
  esac
}

summary__colorize() {
  local color="${1:-}"
  local text="${2:-}"
  if [ "${SUMMARY_IS_TTY}" -eq 1 ] && [ -n "${color}" ]; then
    printf '%s%s%s' "${color}" "${text}" "${SUMMARY_COLOR_RESET}"
  else
    printf '%s' "${text}"
  fi
}

summary__render_section() {
  local title="${1:-}"
  if [ -z "${title}" ]; then
    return 0
  fi
  summary__colorize "${SUMMARY_COLOR_SECTION}" "${title}"
}

summary__render_step() {
  local status="${1}" label="${2}"
  local symbol color text
  symbol="$(summary__status_symbol "${status}")"
  text="${symbol} ${label}"
  color="$(summary__status_color "${status}")"
  printf '  %s\n' "$(summary__colorize "${color}" "${text}")"
}

summary__render_kv() {
  local key="${1}" value="${2}"
  local key_text
  if [ "${SUMMARY_IS_TTY}" -eq 1 ] && [ -n "${SUMMARY_COLOR_DIM}" ]; then
    key_text="$(summary__colorize "${SUMMARY_COLOR_DIM}" "${key}")"
  else
    key_text="${key}"
  fi
  printf '    %s: %s\n' "${key_text}" "${value}"
}

summary__render() {
  local output='' line type rest status label key value after_header=1
  local data="${SUMMARY_DATA%$'\n'}"

  output+='Summary'$'\n'
  output+='======='$'\n'

  while IFS= read -r line; do
    [ -n "${line}" ] || continue
    type="${line%%|*}"
    rest="${line#*|}"
    case "${type}" in
      S)
        if [ "${after_header}" -eq 1 ]; then
          output+=$'\n'
          after_header=0
        else
          output+=$'\n'
        fi
        output+="$(summary__render_section "${rest}")"$'\n'
        ;;
      T)
        if [ "${after_header}" -eq 1 ]; then
          output+=$'\n'
          after_header=0
        fi
        status="${rest%%|*}"
        label="${rest#*|}"
        output+="$(summary__render_step "${status}" "${label}")"
        ;;
      K)
        if [ "${after_header}" -eq 1 ]; then
          output+=$'\n'
          after_header=0
        fi
        key="${rest%%|*}"
        value="${rest#*|}"
        output+="$(summary__render_kv "${key}" "${value}")"
        ;;
      *)
        ;;
    esac
  done <<< "${data}"

  printf '%s' "${output}"
}

summary__ensure_summary_file() {
  if [ -z "${SUGARKUBE_SUMMARY_FILE:-}" ]; then
    return 1
  fi
  local dir
  dir="$(dirname "${SUGARKUBE_SUMMARY_FILE}")"
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}"
  fi
  return 0
}

summary__emit_impl() {
  if [ "${SUMMARY_EMITTED}" -eq 1 ]; then
    return 0
  fi
  SUMMARY_EMITTED=1

  if [ "${SUMMARY_HAS_ITEMS}" -eq 0 ]; then
    return 0
  fi

  local rendered
  rendered="$(summary__render)"
  if [ -z "${rendered}" ]; then
    return 0
  fi

  if [ -n "${SUGARKUBE_SUMMARY_FILE:-}" ]; then
    summary__ensure_summary_file || true
    printf '%s\n' "${rendered}" | tee -a "${SUGARKUBE_SUMMARY_FILE}" >&1
  else
    printf '%s\n' "${rendered}"
  fi
}

summary__emit_trap() {
  summary::emit || true
}

summary__init_impl() {
  SUMMARY_DATA=""
  SUMMARY_HAS_ITEMS=0
  SUMMARY_EMITTED=0

  if [ -t 1 ] && [ "${TERM:-}" != "dumb" ]; then
    SUMMARY_IS_TTY=1
  else
    SUMMARY_IS_TTY=0
  fi

  SUMMARY_COLOR_RESET=""
  SUMMARY_COLOR_SECTION=""
  SUMMARY_COLOR_DIM=""
  SUMMARY_COLOR_OK=""
  SUMMARY_COLOR_WARN=""
  SUMMARY_COLOR_FAIL=""
  SUMMARY_COLOR_SKIP=""

  if [ "${SUMMARY_IS_TTY}" -eq 1 ] && command -v tput >/dev/null 2>&1; then
    SUMMARY_COLOR_RESET="$(tput sgr0 2>/dev/null || printf '')"
    SUMMARY_COLOR_SECTION="$(tput bold 2>/dev/null || printf '')"
    SUMMARY_COLOR_DIM="$(tput dim 2>/dev/null || printf '')"
    SUMMARY_COLOR_OK="$(tput setaf 2 2>/dev/null || printf '')"
    SUMMARY_COLOR_WARN="$(tput setaf 3 2>/dev/null || printf '')"
    SUMMARY_COLOR_FAIL="$(tput setaf 1 2>/dev/null || printf '')"
    SUMMARY_COLOR_SKIP="$(tput setaf 4 2>/dev/null || printf '')"
  fi

  SUMMARY_INITIALIZED=1

  if [ "${SUMMARY_TRAP_SET}" -eq 0 ]; then
    trap 'summary__emit_trap' EXIT
    SUMMARY_TRAP_SET=1
  fi
}

summary__ensure_initialized() {
  if [ "${SUMMARY_INITIALIZED}" -eq 0 ]; then
    summary::init
  fi
}

summary::init() {
  summary__call_with_safe_opts summary__init_impl
}

summary::section() {
  summary__ensure_initialized
  local title
  title="$(summary__clean_text "${1:-}")"
  [ -n "${title}" ] || return 0
  summary__append_line "S|${title}"
}

summary::step() {
  summary__ensure_initialized
  local status_raw="${1:-}" label_raw="${2:-}"
  [ -n "${label_raw}" ] || return 0
  local status="${status_raw^^}"
  case "${status}" in
    OK|WARN|FAIL|SKIP) ;;
    *) status="WARN" ;;
  esac
  local label
  label="$(summary__clean_text "${label_raw}")"
  summary__append_line "T|${status}|${label}"
}

summary::kv() {
  summary__ensure_initialized
  local key value
  key="$(summary__clean_text "${1:-}")"
  value="$(summary__clean_text "${2:-}")"
  [ -n "${key}" ] || return 0
  summary__append_line "K|${key}|${value}"
}

summary::emit() {
  summary__call_with_safe_opts summary__emit_impl
}
