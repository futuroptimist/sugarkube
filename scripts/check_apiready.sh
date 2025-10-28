#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

SERVER_HOST="${SERVER_HOST:-${1:-}}"
if [ -n "${SERVER_HOST}" ] && [ "$#" -gt 0 ]; then
  shift || true
fi
SERVER_PORT="${SERVER_PORT:-${1:-6443}}"
if [ "$#" -gt 0 ]; then
  shift || true
fi
SERVER_IP="${SERVER_IP:-}"
TIMEOUT_RAW="${TIMEOUT:-120}"
POLL_INTERVAL_RAW="${POLL_INTERVAL:-2}"

cleanup_files() {
  if [ -n "${body_file:-}" ] && [ -f "${body_file}" ]; then
    rm -f "${body_file}"
  fi
  if [ -n "${error_file:-}" ] && [ -f "${error_file}" ]; then
    rm -f "${error_file}"
  fi
}

trap cleanup_files EXIT

escape_log_value() {
  printf '%s' "$1" | sed 's/"/\\"/g'
}

require_server_host() {
  if [ -z "${SERVER_HOST}" ]; then
    echo "SERVER_HOST is required" >&2
    exit 2
  fi
}

resolve_positive_int() {
  local value="$1"
  python3 - "$value" <<'PY'
import math
import sys

raw = sys.argv[1]
try:
    numeric = float(raw)
except ValueError:
    print("INVALID")
    sys.exit(0)
if numeric <= 0:
    print("INVALID")
    sys.exit(0)
print(str(int(math.ceil(numeric))))
PY
}

resolve_positive_float() {
  local value="$1"
  python3 - "$value" <<'PY'
import sys
raw = sys.argv[1]
try:
    numeric = float(raw)
except ValueError:
    print("INVALID")
    sys.exit(0)
if numeric <= 0:
    print("INVALID")
    sys.exit(0)
print(str(numeric))
PY
}

validate_ready_body() {
  python3 - <<'PY'
import sys

lines = [line.strip() for line in sys.stdin.read().splitlines()]
seen_ok = False
for line in lines:
    if not line:
        continue
    if line == "readyz check passed":
        seen_ok = True
        continue
    if line == "ok":
        seen_ok = True
        continue
    if line.endswith(" ok"):
        seen_ok = True
        continue
    sys.exit(1)
if not seen_ok:
    sys.exit(1)
PY
}

require_server_host

body_file="$(mktemp)"
error_file="$(mktemp)"

TIMEOUT_SECS="$(resolve_positive_int "${TIMEOUT_RAW}")"
if [ "${TIMEOUT_SECS}" = "INVALID" ]; then
  echo "Invalid TIMEOUT: ${TIMEOUT_RAW}" >&2
  exit 2
fi

POLL_INTERVAL="$(resolve_positive_float "${POLL_INTERVAL_RAW}")"
if [ "${POLL_INTERVAL}" = "INVALID" ]; then
  echo "Invalid POLL_INTERVAL: ${POLL_INTERVAL_RAW}" >&2
  exit 2
fi

start_epoch="$(date +%s)"
end_epoch=$((start_epoch + TIMEOUT_SECS))

attempt=0
last_status=""
last_reason=""

while :; do
  attempt=$((attempt + 1))
  : >"${body_file}"
  : >"${error_file}"

  curl_status=0
  curl_args=(-k -sS --show-error -o "${body_file}" -w '%{http_code}')
  if [ -n "${SERVER_IP}" ]; then
    curl_args+=(--resolve "${SERVER_HOST}:${SERVER_PORT}:${SERVER_IP}")
  fi
  curl_args+=("https://${SERVER_HOST}:${SERVER_PORT}/readyz?verbose")

  http_code="$(curl "${curl_args[@]}" 2>"${error_file}")" || curl_status=$?
  if [ -z "${http_code}" ]; then
    http_code="000"
  fi

  if [ "${curl_status}" -eq 0 ] && [ "${http_code}" = "200" ]; then
    if validate_ready_body <"${body_file}"; then
      elapsed=$(( $(date +%s) - start_epoch ))
      log_fields=(
        "outcome=ok"
        "host=\"$(escape_log_value "${SERVER_HOST}")\""
        "port=\"$(escape_log_value "${SERVER_PORT}")\""
        "attempts=${attempt}"
        "elapsed=${elapsed}"
        "status=${http_code}"
      )
      if [ -n "${SERVER_IP}" ]; then
        log_fields+=("ip=\"$(escape_log_value "${SERVER_IP}")\"")
      fi
      log_kv info apiready "${log_fields[@]}" >&2
      exit 0
    fi
    last_reason="body_not_ok"
  else
    last_reason="curl_failed"
  fi
  last_status="${http_code}:${curl_status}"

  retry_fields=(
    "outcome=retry"
    "host=\"$(escape_log_value "${SERVER_HOST}")\""
    "port=\"$(escape_log_value "${SERVER_PORT}")\""
    "attempt=${attempt}"
    "status=${http_code}"
    "curl_status=${curl_status}"
    "reason=${last_reason}"
  )
  if [ -n "${SERVER_IP}" ]; then
    retry_fields+=("ip=\"$(escape_log_value "${SERVER_IP}")\"")
  fi
  log_kv debug apiready "${retry_fields[@]}" >&2

  now="$(date +%s)"
  if [ "${now}" -ge "${end_epoch}" ]; then
    elapsed=$((now - start_epoch))
    if [ -z "${last_reason}" ]; then
      last_reason="timeout"
    fi
    failure_fields=(
      "outcome=timeout"
      "host=\"$(escape_log_value "${SERVER_HOST}")\""
      "port=\"$(escape_log_value "${SERVER_PORT}")\""
      "attempts=${attempt}"
      "elapsed=${elapsed}"
      "last_status=\"$(escape_log_value "${last_status}")\""
      "reason=${last_reason}"
    )
    if [ -n "${SERVER_IP}" ]; then
      failure_fields+=("ip=\"$(escape_log_value "${SERVER_IP}")\"")
    fi
    log_kv info apiready "${failure_fields[@]}" >&2
    exit 1
  fi

  sleep "${POLL_INTERVAL}"
done
