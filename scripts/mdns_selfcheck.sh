#!/bin/sh
if ! set -Eeuo pipefail 2>/dev/null; then
  if ! set -euo pipefail 2>/dev/null; then
    set -eu
  fi
fi

SERVICE_CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
SERVICE_ENV="${SUGARKUBE_ENV:-dev}"
EXPECTED_HOST="${SUGARKUBE_EXPECTED_HOST:-}"
EXPECTED_IPV4="${SUGARKUBE_EXPECTED_IPV4:-}"
ATTEMPTS="${SUGARKUBE_SELFCHK_ATTEMPTS:-12}"
BACKOFF_START_MS="${SUGARKUBE_SELFCHK_BACKOFF_START_MS:-500}"
BACKOFF_CAP_MS="${SUGARKUBE_SELFCHK_BACKOFF_CAP_MS:-5000}"
JITTER_FRACTION="${JITTER:-0.2}"

case "${ATTEMPTS}" in
  ''|*[!0-9]*) ATTEMPTS=1 ;;
  0) ATTEMPTS=1 ;;
esac
case "${BACKOFF_START_MS}" in
  ''|*[!0-9]*) BACKOFF_START_MS=500 ;;
esac
case "${BACKOFF_CAP_MS}" in
  ''|*[!0-9]*) BACKOFF_CAP_MS=5000 ;;
esac

if [ -z "${EXPECTED_HOST}" ]; then
  >&2 printf 'event=mdns_selfcheck outcome=miss attempt=0 reason=missing_expected_host\n'
  exit 2
fi

if ! command -v avahi-browse >/dev/null 2>&1; then
  >&2 printf 'event=mdns_selfcheck outcome=miss attempt=0 reason=avahi_browse_missing\n'
  exit 3
fi
if ! command -v avahi-resolve >/dev/null 2>&1; then
  >&2 printf 'event=mdns_selfcheck outcome=miss attempt=0 reason=avahi_resolve_missing\n'
  exit 3
fi

SERVICE_TYPE="_k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}._tcp"
INSTANCE_PREFIX="k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}@${EXPECTED_HOST}"

script_start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

strip_quotes() {
  local value="$1"
  case "${value}" in
    "*"|'*')
      if [ "${#value}" -ge 2 ]; then
        value="${value#?}"
        value="${value%?}"
        printf '%s' "${value}"
        return
      fi
      ;;
  esac
  printf '%s' "${value}"
}

parse_browse() {
  local target_instance=""
  local srv_host=""
  local srv_port=""

  while IFS=';' read -r record _iface _proto instance type domain host addr port rest; do
    [ "${record}" = "=" ] || continue
    instance="$(strip_quotes "${instance}")"
    type="$(strip_quotes "${type}")"
    domain="$(strip_quotes "${domain}")"
    host="$(strip_quotes "${host}")"
    port="$(strip_quotes "${port}")"

    case "${instance}" in
      "${INSTANCE_PREFIX} (bootstrap)"|"${INSTANCE_PREFIX} (server)")
        target_instance="${instance}"
        srv_host="${host}"
        srv_port="${port}"
        break
        ;;
    esac
  done

  if [ -n "${target_instance}" ] && [ -n "${srv_host}" ]; then
    printf '%s\n' "${target_instance}|${srv_host}|${srv_port}"
  fi
}

resolve_host() {
  local host="$1"
  if [ -z "${host}" ]; then
    return 1
  fi

  local output
  if ! output="$(avahi-resolve -n "${host}" 2>/dev/null)"; then
    return 1
  fi

  local any_addr=""
  local ipv4_addr=""
  local line field
  while IFS= read -r line; do
    [ -n "${line}" ] || continue
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

compute_delay_ms() {
  python3 - "$@" <<'PY'
import random
import sys

try:
    attempt = int(sys.argv[1])
except ValueError:
    attempt = 1
try:
    start = int(sys.argv[2])
except ValueError:
    start = 0
try:
    cap = int(sys.argv[3])
except ValueError:
    cap = 0
try:
    jitter = float(sys.argv[4])
except ValueError:
    jitter = 0.0

if attempt < 1:
    attempt = 1
if start < 0:
    start = 0
if cap < 0:
    cap = 0
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
print(delay)
PY
}

attempt=1
last_reason=""
while [ "${attempt}" -le "${ATTEMPTS}" ]; do
  browse_output="$(avahi-browse -rt "${SERVICE_TYPE}" 2>/dev/null || true)"
  parsed="$(printf '%s\n' "${browse_output}" | parse_browse || true)"
  if [ -n "${parsed}" ]; then
    srv_host="${parsed#*|}"
    srv_host="${srv_host%%|*}"
    srv_port="${parsed##*|}"
    if [ -z "${srv_host}" ]; then
      last_reason="empty_srv_host"
    else
      resolved="$(resolve_host "${srv_host}" || true)"
      status=$?
      if [ "${status}" -eq 0 ] && [ -n "${resolved}" ]; then
        resolved_ipv4="${resolved##*|}"
        elapsed_ms="$(python3 - <<'PY'
import sys, time
start = int(sys.argv[1])
print(int(time.time() * 1000) - start)
PY
"${script_start_ms}")"
        printf 'event=mdns_selfcheck outcome=ok host=%s ipv4=%s port=%s attempts=%s ms_elapsed=%s\n' \
          "${srv_host}" "${resolved_ipv4}" "${srv_port}" "${attempt}" "${elapsed_ms}"
        exit 0
      fi
      if [ "${status}" -eq 2 ]; then
        last_reason="ipv4_mismatch"
      else
        last_reason="resolve_failed"
      fi
    fi
  else
    if [ -z "${browse_output}" ]; then
      last_reason="browse_empty"
    else
      last_reason="instance_not_found"
    fi
  fi

  >&2 printf 'event=mdns_selfcheck outcome=miss attempt=%s reason=%s\n' "${attempt}" "${last_reason}"

  if [ "${attempt}" -ge "${ATTEMPTS}" ]; then
    break
  fi

  delay_ms="$(compute_delay_ms "${attempt}" "${BACKOFF_START_MS}" "${BACKOFF_CAP_MS}" "${JITTER_FRACTION}" || echo 0)"
  case "${delay_ms}" in
    ''|*[!0-9]*) delay_ms=0 ;;
  esac
  if [ "${delay_ms}" -gt 0 ]; then
    delay_s="$(python3 - <<'PY'
import sys
try:
    delay = int(sys.argv[1])
except ValueError:
    delay = 0
print('{:.3f}'.format(delay / 1000.0))
PY
"${delay_ms}")"
    sleep "${delay_s}"
  fi
  attempt=$((attempt + 1))
done

elapsed_ms="$(python3 - <<'PY'
import sys, time
start = int(sys.argv[1])
print(int(time.time() * 1000) - start)
PY
"${script_start_ms}")"
>&2 printf 'event=mdns_selfcheck outcome=fail attempts=%s reason=%s ms_elapsed=%s\n' "${ATTEMPTS}" "${last_reason:-unknown}" "${elapsed_ms}"
exit 1
