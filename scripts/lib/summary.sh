#!/usr/bin/env bash

# Summary reporting helpers. Designed to be sourced by interactive shells and
# non-interactive scripts alike. The functions are safe to call even when the
# summary feature is disabled (SUGARKUBE_SUMMARY_FILE unset or unwritable).

if [ -n "${SUGARKUBE_SUMMARY_LOADED:-}" ]; then
  return 0 2>/dev/null || exit 0
fi
export SUGARKUBE_SUMMARY_LOADED=1

summary_enabled() {
  [ -n "${SUGARKUBE_SUMMARY_FILE:-}" ] && [ "${SUGARKUBE_SUMMARY_SUPPRESS:-0}" != "1" ]
}

summary__ensure_file() {
  if ! summary_enabled; then
    return 1
  fi
  local dir
  dir="$(dirname "${SUGARKUBE_SUMMARY_FILE}")"
  if [ ! -d "${dir}" ]; then
    mkdir -p "${dir}" 2>/dev/null || true
  fi
  if [ ! -f "${SUGARKUBE_SUMMARY_FILE}" ]; then
    : >"${SUGARKUBE_SUMMARY_FILE}" 2>/dev/null || return 1
  fi
  return 0
}

summary_now_ms() {
  python3 - <<'PY' 2>/dev/null || date +%s%3N
import time
print(int(time.time() * 1000))
PY
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

summary_sanitize_note() {
  local note="$1"
  note="${note//$'\n'/' '}"
  note="${note//$'\r'/' '}"
  printf '%s' "${note}"
}

summary_step() {
  local name="$1"
  local status="${2:-OK}"
  local duration_ms="${3:-0}"
  local note="${4:-}"

  if ! summary_enabled; then
    return 0
  fi
  if ! summary__ensure_file; then
    return 0
  fi

  case "${status}" in
    ok|Ok|oK) status="OK" ;;
    warn|Warn) status="WARN" ;;
    fail|Fail) status="FAIL" ;;
    skip|Skip) status="SKIP" ;;
    OK|WARN|FAIL|SKIP) ;;
    *) status="${status^^}" ;;
  esac

  case "${duration_ms}" in
    ''|*[!0-9-]*) duration_ms=0 ;;
  esac

  local timestamp
  timestamp="$(summary_now_ms)"
  note="$(summary_sanitize_note "${note}")"

  printf '%s\t%s\t%s\t%s\t%s\n' \
    "${timestamp}" "${duration_ms}" "${status}" "${name}" "${note}" \
    >>"${SUGARKUBE_SUMMARY_FILE}" 2>/dev/null || true
}

summary_skip() {
  local name="$1"
  local note="${2:-}"
  summary_step "${name}" "SKIP" 0 "${note}"
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

  local name="$1"
  shift

  local start_ms status duration exit_code
  start_ms="$(summary_now_ms)"

  set +e
  "$@"
  exit_code=$?
  set -e

  duration="$(summary_elapsed_ms "${start_ms}")"
  status="OK"
  if [ "${exit_code}" -ne 0 ]; then
    status="FAIL"
  fi

  summary_step "${name}" "${status}" "${duration}" "${note}"
  return "${exit_code}"
}

summary_display_width() {
  SUMMARY_TMP_TEXT="${1-}" python3 - <<'PY'
import os
import re
import sys
import unicodedata
text = os.environ.get("SUMMARY_TMP_TEXT", "")
ansi_re = re.compile(r"\x1B\[[0-9;]*m")
text = ansi_re.sub("", text)
width = 0
for ch in text:
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        continue
    if unicodedata.combining(ch):
        continue
    if unicodedata.east_asian_width(ch) in ("F", "W"):
        width += 2
    else:
        width += 1
print(width)
PY
}

summary_repeat_char() {
  local char="$1"
  local count="$2"
  local result=""
  while [ "${count}" -gt 0 ]; do
    result+="${char}"
    count=$((count - 1))
  done
  printf '%s' "${result}"
}

summary_format_duration() {
  local ms="$1"
  python3 - <<'PY' "${ms}"
import sys
try:
    value = int(sys.argv[1])
except (IndexError, ValueError):
    value = 0
if value < 0:
    value = 0
seconds, millis = divmod(value, 1000)
minutes, seconds = divmod(seconds, 60)
if minutes:
    rem = seconds + millis / 1000.0
    print(f"{minutes}m {rem:.1f}s")
elif value >= 1000:
    print(f"{seconds + millis / 1000.0:.1f}s")
else:
    print(f"{value}ms")
PY
}

summary_status_display() {
  local status="$1"
  case "${status}" in
    OK)
      printf '\033[32m✅ OK\033[0m'
      ;;
    WARN)
      printf '\033[33m⚠️ WARN\033[0m'
      ;;
    FAIL)
      printf '\033[31m❌ FAIL\033[0m'
      ;;
    SKIP)
      printf '\033[34m⏭️ SKIP\033[0m'
      ;;
    *)
      printf '%s' "${status}"
      ;;
  esac
}

summary_status_plain() {
  local status="$1"
  case "${status}" in
    OK) printf '✅ OK' ;;
    WARN) printf '⚠️ WARN' ;;
    FAIL) printf '❌ FAIL' ;;
    SKIP) printf '⏭️ SKIP' ;;
    *) printf '%s' "${status}" ;;
  esac
}

summary_pad() {
  local text="$1"
  local width="$2"
  local actual padding
  actual="$(summary_display_width "${text}")"
  case "${actual}" in
    ''|*[!0-9]*) actual=0 ;;
  esac
  padding=$((width - actual))
  if [ "${padding}" -lt 0 ]; then
    padding=0
  fi
  printf '%s' "${text}"
  if [ "${padding}" -gt 0 ]; then
    printf '%*s' "${padding}" ''
  fi
}

summary_finalize() {
  if ! summary_enabled; then
    return 0
  fi
  if [ ! -s "${SUGARKUBE_SUMMARY_FILE}" ]; then
    return 0
  fi

  local -a names=()
  local -a status_codes=()
  local -a status_display=()
  local -a status_plain=()
  local -a durations=()
  local -a notes=()

  local line
  while IFS=$'\t' read -r _start_ms duration status name note; do
    [ -n "${name}" ] || continue
    names+=("${name}")
    status_codes+=("${status}")
    status_display+=("$(summary_status_display "${status}")")
    status_plain+=("$(summary_status_plain "${status}")")
    durations+=("$(summary_format_duration "${duration}")")
    notes+=("${note}")
  done <"${SUGARKUBE_SUMMARY_FILE}"

  local count="${#names[@]}"
  if [ "${count}" -eq 0 ]; then
    return 0
  fi

  local step_width status_width duration_width
  step_width="$(summary_display_width "Step")"
  status_width="$(summary_display_width "Status")"
  duration_width="$(summary_display_width "Duration")"

  local idx note extra step_label plain_status
  for idx in "${!names[@]}"; do
    step_label="${names[idx]}"
    note="${notes[idx]}"
    if [ -n "${note}" ]; then
      step_label+=" "
      step_label+="\033[2m(${note})\033[0m"
    fi
    names[idx]="${step_label}"
    extra="$(summary_display_width "${step_label}")"
    if [ "${extra}" -gt "${step_width}" ]; then
      step_width="${extra}"
    fi
    plain_status="${status_plain[idx]}"
    extra="$(summary_display_width "${plain_status}")"
    if [ "${extra}" -gt "${status_width}" ]; then
      status_width="${extra}"
    fi
    extra="$(summary_display_width "${durations[idx]}")"
    if [ "${extra}" -gt "${duration_width}" ]; then
      duration_width="${extra}"
    fi
  done

  local step_total status_total duration_total
  step_total=$((step_width + 2))
  status_total=$((status_width + 2))
  duration_total=$((duration_width + 2))

  printf '\n'
  printf '┏%s┳%s┳%s┓\n' \
    "$(summary_repeat_char '━' "${step_total}")" \
    "$(summary_repeat_char '━' "${status_total}")" \
    "$(summary_repeat_char '━' "${duration_total}")"
  printf '┃ '
  summary_pad "Step" "${step_width}"
  printf ' ┃ '
  summary_pad "Status" "${status_width}"
  printf ' ┃ '
  summary_pad "Duration" "${duration_width}"
  printf ' ┃\n'
  printf '┣%s╋%s╋%s┫\n' \
    "$(summary_repeat_char '━' "${step_total}")" \
    "$(summary_repeat_char '━' "${status_total}")" \
    "$(summary_repeat_char '━' "${duration_total}")"

  for idx in "${!names[@]}"; do
    printf '┃ '
    summary_pad "${names[idx]}" "${step_width}"
    printf ' ┃ '
    summary_pad "${status_display[idx]}" "${status_width}"
    printf ' ┃ '
    summary_pad "${durations[idx]}" "${duration_width}"
    printf ' ┃\n'
  done

  printf '┗%s┻%s┻%s┛\n' \
    "$(summary_repeat_char '━' "${step_total}")" \
    "$(summary_repeat_char '━' "${status_total}")" \
    "$(summary_repeat_char '━' "${duration_total}")"
}
