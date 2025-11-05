#!/usr/bin/env bash
# shellcheck disable=SC3040,SC3041,SC3043
set -euo pipefail

set -E

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

if [ "${SUGARKUBE_MDNS_DBUS:-0}" != "1" ]; then
  log_debug mdns_selfcheck_dbus outcome=skip reason=dbus_flag_disabled
  exit 2
fi

if ! command -v gdbus >/dev/null 2>&1; then
  log_debug mdns_selfcheck_dbus outcome=skip reason=gdbus_missing
  exit 2
fi

SERVICE_CLUSTER="${SUGARKUBE_CLUSTER:-sugar}"
SERVICE_ENV="${SUGARKUBE_ENV:-dev}"
EXPECTED_HOST="${SUGARKUBE_EXPECTED_HOST:-}"
EXPECTED_IPV4="${SUGARKUBE_EXPECTED_IPV4:-}"
EXPECTED_ROLE="${SUGARKUBE_EXPECTED_ROLE:-}"
EXPECTED_PHASE="${SUGARKUBE_EXPECTED_PHASE:-}"
ATTEMPTS="${SUGARKUBE_SELFCHK_ATTEMPTS:-12}"
BACKOFF_START_MS="${SUGARKUBE_SELFCHK_BACKOFF_START_MS:-500}"
BACKOFF_CAP_MS="${SUGARKUBE_SELFCHK_BACKOFF_CAP_MS:-5000}"
JITTER_FRACTION="${JITTER:-0.2}"
SERVICE_DOMAIN="${SUGARKUBE_MDNS_DOMAIN:-local}"

script_start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

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
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck_failure outcome=miss reason=missing_expected_host attempt=0 ms_elapsed="${elapsed_ms}" >&2
  exit 2
fi

SERVICE_TYPE="_k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}._tcp"
INSTANCE_PREFIX="k3s-${SERVICE_CLUSTER}-${SERVICE_ENV}@${EXPECTED_HOST}"

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

call_service_browser() {
  python3 - "${SERVICE_TYPE}" "${SERVICE_DOMAIN}" <<'PY'
import ast
import re
import subprocess
import sys

service_type = sys.argv[1]
service_domain = sys.argv[2]
cmd = [
    "gdbus",
    "call",
    "--system",
    "--dest",
    "org.freedesktop.Avahi",
    "--object-path",
    "/",
    "--method",
    "org.freedesktop.Avahi.Server.ServiceBrowserNew",
    "int32:-1",
    "int32:-1",
    service_type,
    service_domain,
    "uint32:0",
]
proc = subprocess.run(cmd, capture_output=True, text=True)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr)
    sys.exit(proc.returncode)
output = proc.stdout.strip()
clean = re.sub(r'\bobjectpath\s*:?', '', output)
value = ast.literal_eval(clean)
if isinstance(value, (list, tuple)) and len(value) == 1:
    value = value[0]
if not value:
    sys.exit(1)
print(value)
PY
}

resolve_service() {
  local instance="$1"
  python3 - "$instance" "${SERVICE_TYPE}" "${SERVICE_DOMAIN}" <<'PY'
import ast
import json
import re
import subprocess
import sys

instance = sys.argv[1]
service_type = sys.argv[2]
service_domain = sys.argv[3]
cmd = [
    "gdbus",
    "call",
    "--system",
    "--dest",
    "org.freedesktop.Avahi",
    "--object-path",
    "/",
    "--method",
    "org.freedesktop.Avahi.Server.ResolveService",
    "int32:-1",
    "int32:-1",
    instance,
    service_type,
    service_domain,
    "int32:-1",
    "uint32:0",
]
proc = subprocess.run(cmd, capture_output=True, text=True)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr)
    sys.exit(proc.returncode)
output = proc.stdout.strip()
clean = re.sub(
    r'\b(?:int16|int32|int64|uint16|uint32|uint64|byte|double|boolean|objectpath)\s*:?',
    '',
    output,
)
clean = re.sub(r'\barray\s*(?=\[)', '', clean)
value = ast.literal_eval(clean)
if isinstance(value, (list, tuple)) and len(value) == 1:
    value = value[0]
iface, proto, name, stype, domain, host, aproto, address, port, txt, flags = value
if isinstance(txt, tuple):
    txt = list(txt)
result = {
    "interface": iface,
    "protocol": proto,
    "name": name,
    "type": stype,
    "domain": domain,
    "host": host,
    "aprotocol": aproto,
    "address": address,
    "port": port,
    "txt": list(txt),
    "flags": flags,
}
print(json.dumps(result))
PY
}

resolve_host_name() {
  local host="$1"
  local aproto="$2"
  python3 - "$host" "$aproto" <<'PY'
import ast
import json
import re
import subprocess
import sys

host = sys.argv[1]
aproto = sys.argv[2]
cmd = [
    "gdbus",
    "call",
    "--system",
    "--dest",
    "org.freedesktop.Avahi",
    "--object-path",
    "/",
    "--method",
    "org.freedesktop.Avahi.Server.ResolveHostName",
    "int32:-1",
    "int32:-1",
    host,
    f"int32:{aproto}",
    "uint32:0",
]
proc = subprocess.run(cmd, capture_output=True, text=True)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr)
    sys.exit(proc.returncode)
output = proc.stdout.strip()
clean = re.sub(
    r'\b(?:int16|int32|int64|uint16|uint32|uint64|byte|double|boolean|objectpath)\s*:?',
    '',
    output,
)
value = ast.literal_eval(clean)
if isinstance(value, (list, tuple)) and len(value) == 1:
    value = value[0]
iface, proto, name, address, aprotocol, flags = value
print(json.dumps({
    "name": name,
    "address": address,
    "aprotocol": aprotocol,
    "flags": flags,
}))
PY
}

# Wait for Avahi dbus service using gdbus introspect with retry logic
# Detects ServiceUnknown errors and retries until service is available  
# Returns 0 if Avahi is ready, 1 if ServiceUnknown persists, 2 if other error/skip
wait_for_avahi_dbus_gdbus() {
  local max_attempts="${1:-10}"
  local attempt=0
  
  while [ "${attempt}" -lt "${max_attempts}" ]; do
    attempt=$((attempt + 1))
    
    # Try gdbus introspect to check if Avahi service is available
    # Capture both stdout and stderr to check for ServiceUnknown error
    local error_output
    error_output="$(gdbus introspect --system --dest org.freedesktop.Avahi --object-path / 2>&1)"
    local gdbus_status=$?
    
    if [ "${gdbus_status}" -eq 0 ]; then
      # Success - Avahi is ready
      local elapsed_ms
      elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
      log_info mdns_selfcheck event=avahi_dbus_ready outcome=ok attempts="${attempt}" ms_elapsed="${elapsed_ms}"
      return 0
    fi
    
    # Command failed - check if it's a retryable ServiceUnknown error
    if [[ "${error_output}" =~ ServiceUnknown ]]; then
      # Service not ready yet, retry after brief sleep
      log_debug mdns_selfcheck event=avahi_dbus_wait attempt="${attempt}" status=not_ready
      sleep 0.5
      continue
    fi
    
    # Other error (gdbus not available, introspect not supported, etc) - skip this check
    # Log debug and return 2 to indicate we should skip this check method
    log_debug mdns_selfcheck event=avahi_dbus_introspect_unsupported attempt="${attempt}"
    return 2
  done
  
  # Max attempts reached without success
  local elapsed_ms
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck event=avahi_dbus_timeout attempts="${max_attempts}" ms_elapsed="${elapsed_ms}" severity=error
  return 1
}

# Try gdbus introspect to wait for Avahi service if it's supported
# This handles the case where Avahi is starting up and returns ServiceUnknown
wait_status=0
wait_for_avahi_dbus_gdbus 10 || wait_status=$?

if [ "${wait_status}" -eq 1 ]; then
  # ServiceUnknown persisted - Avahi not starting up
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck outcome=miss reason=avahi_dbus_wait_failed attempt=0 ms_elapsed="${elapsed_ms}" >&2
  exit 1
elif [ "${wait_status}" -eq 2 ]; then
  # Introspect not supported/available - this is OK, continue without it
  # The gdbus call methods will be used directly
  log_debug mdns_selfcheck event=skipping_introspect_wait reason=not_supported
fi

# If wait_status is 0, gdbus introspect succeeded and Avahi is ready
# If wait_status is 2, introspect not supported but we can proceed
# Either way, continue with the rest of the script

script_start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

if ! call_service_browser >/dev/null 2>&1; then
  status=$?
  if [ "${status}" -eq 126 ] || [ "${status}" -eq 127 ]; then
    log_debug mdns_selfcheck_dbus outcome=skip reason=gdbus_unavailable
    exit 2
  fi
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info mdns_selfcheck outcome=miss reason=browser_create_failed attempt=0 ms_elapsed="${elapsed_ms}" >&2
  exit 1
fi

attempt=1
last_reason=""
miss_count=0

if [ -n "${EXPECTED_ROLE}" ]; then
  set -- "${INSTANCE_PREFIX} (${EXPECTED_ROLE})"
else
  set -- "${INSTANCE_PREFIX} (server)" "${INSTANCE_PREFIX} (bootstrap)"
fi

while [ "${attempt}" -le "${ATTEMPTS}" ]; do
  for candidate in "$@"; do
    if ! result_json="$(resolve_service "${candidate}" 2>/dev/null)"; then
      status=$?
      if [ "${status}" -eq 126 ] || [ "${status}" -eq 127 ]; then
        log_debug mdns_selfcheck_dbus outcome=skip reason=gdbus_unavailable attempt="${attempt}"
        exit 2
      fi
      last_reason="resolve_failed"
      continue
    fi
    if [ -z "${result_json}" ] || [ "${result_json}" = "null" ]; then
      last_reason="resolve_empty"
      continue
    fi
    resolved_host="$(
      python3 - "${result_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(payload.get("host", ""))
PY
    )"
    resolved_port="$(
      python3 - "${result_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(payload.get("port", ""))
PY
    )"
    resolved_address="$(
      python3 - "${result_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(payload.get("address", ""))
PY
    )"
    txt_payload="$(
      python3 - "${result_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print('\n'.join(payload.get("txt", [])))
PY
    )"
    txt_for_trace="$(printf '%s' "${txt_payload}" | tr '\n' ' ' | tr -s ' ' | sed 's/"/\\"/g')"
    log_trace mdns_selfcheck_dbus \
      attempt="${attempt}" \
      candidate="${candidate}" \
      host="${resolved_host}" \
      port="${resolved_port}" \
      "txt=\"${txt_for_trace}\""

    if [ -z "${resolved_host}" ]; then
      last_reason="empty_srv_host"
      continue
    fi

    if [ "${resolved_host}" != "${EXPECTED_HOST}" ]; then
      last_reason="host_mismatch"
      continue
    fi

    if [ -n "${EXPECTED_ROLE}" ]; then
      if ! printf '%s\n' "${txt_payload}" | grep -F "role=${EXPECTED_ROLE}" >/dev/null; then
        last_reason="role_mismatch"
        continue
      fi
    else
      if ! printf '%s\n' "${txt_payload}" | grep -F "role=server" >/dev/null && \
        ! printf '%s\n' "${txt_payload}" | grep -F "role=bootstrap" >/dev/null; then
        last_reason="role_mismatch"
        continue
      fi
    fi

    if [ -n "${EXPECTED_PHASE}" ] && \
      ! printf '%s\n' "${txt_payload}" | grep -F "phase=${EXPECTED_PHASE}" >/dev/null; then
      last_reason="phase_mismatch"
      continue
    fi

    resolved_ipv4=""
    if name_resolution_json="$(resolve_host_name "${resolved_host}" 0 2>/dev/null)"; then
      resolved_ipv4="$(
        python3 - "${name_resolution_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(payload.get("address", ""))
PY
      )"
    else
      status=$?
      if [ "${status}" -eq 126 ] || [ "${status}" -eq 127 ]; then
        log_debug mdns_selfcheck_dbus \
          outcome=skip \
          reason=gdbus_unavailable \
          attempt="${attempt}" \
          phase=resolve_host
        exit 2
      fi
    fi

    if [ -z "${resolved_ipv4}" ] && [ -n "${EXPECTED_IPV4}" ]; then
      # Attempt unspecified protocol if IPv4 lookup empty
      if name_resolution_json="$(resolve_host_name "${resolved_host}" -1 2>/dev/null)"; then
        resolved_ipv4="$(
          python3 - "${name_resolution_json}" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(payload.get("address", ""))
PY
        )"
      else
        status=$?
        if [ "${status}" -eq 126 ] || [ "${status}" -eq 127 ]; then
          log_debug mdns_selfcheck_dbus \
            outcome=skip \
            reason=gdbus_unavailable \
            attempt="${attempt}" \
            phase=resolve_host
          exit 2
        fi
      fi
    fi

    if [ -n "${EXPECTED_IPV4}" ]; then
      if [ "${resolved_ipv4}" != "${EXPECTED_IPV4}" ]; then
        last_reason="ipv4_mismatch"
        continue
      fi
    fi

    if [ -z "${resolved_ipv4}" ]; then
      resolved_ipv4="${resolved_address}"
    fi

    elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
    log_info mdns_selfcheck \
      outcome=ok \
      host="${resolved_host}" \
      ipv4="${resolved_ipv4}" \
      port="${resolved_port}" \
      attempts="${attempt}" \
      ms_elapsed="${elapsed_ms}"
    exit 0
  done

  miss_count=$((miss_count + 1))
  log_debug mdns_selfcheck \
    outcome=miss \
    attempt="${attempt}" \
    reason="${last_reason}" \
    service_type="${SERVICE_TYPE}"

  if [ "${attempt}" -ge "${ATTEMPTS}" ]; then
    break
  fi

  delay_ms="$(
    compute_delay_ms \
      "${attempt}" \
      "${BACKOFF_START_MS}" \
      "${BACKOFF_CAP_MS}" \
      "${JITTER_FRACTION}" || echo 0
  )"
  case "${delay_ms}" in
    ''|*[!0-9]*) delay_ms=0 ;;
  esac
  if [ "${delay_ms}" -gt 0 ]; then
    delay_s="$(
      python3 - "${delay_ms}" <<'PY'
import sys
try:
    delay = int(sys.argv[1])
except ValueError:
    delay = 0
print('{:.3f}'.format(delay / 1000.0))
PY
    )"
    log_trace mdns_selfcheck_backoff \
      attempt="${attempt}" \
      delay_ms="${delay_ms}" \
      delay_s="${delay_s}"
    sleep "${delay_s}"
  fi
  attempt=$((attempt + 1))

done

elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
log_info mdns_selfcheck \
  outcome=fail \
  attempts="${ATTEMPTS}" \
  misses="${miss_count}" \
  reason="${last_reason:-unknown}" \
  ms_elapsed="${elapsed_ms}" >&2
exit 1
