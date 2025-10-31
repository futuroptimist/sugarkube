#!/bin/sh
# shellcheck disable=SC3040,SC3041,SC3043
set -eu

if (set -o pipefail) 2>/dev/null; then
  set -o pipefail
fi

if (set -E) 2>/dev/null; then
  set -E
fi

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

wait_limit_ms="${AVAHI_DBUS_WAIT_MS:-20000}"
case "${wait_limit_ms}" in
  ''|*[!0-9]*) wait_limit_ms=20000 ;;
  *)
    if [ "${wait_limit_ms}" -lt 0 ]; then
      wait_limit_ms=0
    fi
    ;;
esac

script_start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

avahi_conf_path="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"

dbus_disabled() {
  if [ ! -f "${avahi_conf_path}" ]; then
    return 1
  fi
  if LC_ALL=C grep -Eiq '^[[:space:]]*enable-dbus[[:space:]]*=[[:space:]]*no([[:space:]]|$)' \
    "${avahi_conf_path}"; then
    return 0
  fi
  return 1
}

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

jitter_fraction_raw="${AVAHI_DBUS_JITTER:-0.2}"
jitter_fraction="$({
  python3 - <<'PY' "${jitter_fraction_raw}"
import sys

def clamp(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.2
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value

print(clamp(sys.argv[1] if len(sys.argv) > 1 else 0.2))
PY
} 2>/dev/null)"
case "${jitter_fraction}" in
  ''|*[!0-9.:-]*) jitter_fraction=0.2 ;;
esac

sanitize_kv() {
  # Ensure the sanitizer behaves consistently even on locales where the
  # collating sequence would otherwise make '-' create an invalid range.
  # GNU `tr` treats '-' as a range operator unless it appears first or
  # last in the character set, so explicitly place it at the end.
  LC_ALL=C printf '%s' "$1" \
    | tr '\n\r\t' '   ' \
    | tr -s ' ' ' ' \
    | tr ' ' '_' \
    | tr -cd '[:alnum:]_.:/-'
}

compute_sleep_ms() {
  python3 - "$@" <<'PY'
import random
import sys

def parse_int(idx, default=0):
    try:
        return int(sys.argv[idx])
    except (IndexError, ValueError):
        return default

base = parse_int(1, 100)
cap = parse_int(2, 1000)
remaining = parse_int(3, base)
try:
    jitter = float(sys.argv[4])
except (IndexError, ValueError):
    jitter = 0.0

if base < 1:
    base = 1
if cap > 0 and base > cap:
    base = cap
sleep_ms = base
if remaining > 0 and sleep_ms > remaining:
    sleep_ms = remaining
if sleep_ms < 1:
    sleep_ms = 1
if jitter > 0.0:
    delta = int(sleep_ms * jitter)
    if delta > 0:
        low = sleep_ms - delta
        high = sleep_ms + delta
        if low < 1:
            low = 1
        sleep_ms = random.randint(low, high)
print(sleep_ms)
PY
}

poll_interval_ms=200
poll_cap_ms=2000

if dbus_disabled; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info \
    avahi_dbus_ready \
    outcome=disabled \
    reason=enable_dbus_no \
    severity=info \
    ms_elapsed="${elapsed_ms}"
  exit 2
fi

if ! command -v systemctl >/dev/null 2>&1; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info \
    avahi_dbus_ready \
    outcome=skip \
    reason=systemctl_missing \
    severity=info \
    ms_elapsed="${elapsed_ms}"
  exit 2
fi

if ! command -v busctl >/dev/null 2>&1; then
  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  log_info \
    avahi_dbus_ready \
    outcome=skip \
    reason=busctl_missing \
    severity=info \
    ms_elapsed="${elapsed_ms}"
  exit 2
fi

last_systemctl_state="unknown"
last_systemctl_status=1
last_systemctl_detail=""
last_bus_status="pending"
last_bus_error=""
last_bus_code=1
systemd_absent_hint=0

while :; do
  if dbus_disabled; then
    elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
    log_info \
      avahi_dbus_ready \
      outcome=disabled \
      reason=enable_dbus_no \
      severity=info \
      ms_elapsed="${elapsed_ms}"
    exit 2
  fi

  if systemctl_output="$(systemctl is-active avahi-daemon 2>&1)"; then
    systemctl_status=0
  else
    systemctl_status=$?
  fi
  systemctl_state="$(printf '%s' "${systemctl_output}" | sed -n '1p' | tr -d '\r')"
  systemctl_state="$(printf '%s' "${systemctl_state}" | tr -d '[:space:]')"
  if [ -z "${systemctl_state}" ]; then
    systemctl_state="unknown"
  fi
  last_systemctl_state="${systemctl_state}"
  last_systemctl_status="${systemctl_status}"
  if [ "${systemctl_status}" -ne 0 ] && [ "${systemctl_status}" -ne 3 ]; then
    last_systemctl_detail="${systemctl_output}"
    if printf '%s' "${last_systemctl_detail}" | grep -Eiq \
      'System has not been booted with systemd|Failed to connect to bus|Failed to get D-Bus connection|Systemd service manager is not running'; then
      systemd_absent_hint=1
    fi
  else
    last_systemctl_detail=""
  fi

  systemd_ready=0
  if [ "${systemctl_status}" -eq 0 ] && [ "${systemctl_state}" = "active" ]; then
    systemd_ready=1
  fi

  if [ "${systemd_ready}" -eq 1 ]; then
    busctl_output=""
    busctl_status=0
    if busctl_output="$(busctl \
      --system \
      --timeout=2 \
      call \
      org.freedesktop.Avahi \
      /org/freedesktop/Avahi/Server \
      org.freedesktop.Avahi.Server \
      GetVersionString 2>&1)"; then
      last_bus_status="ok"
      last_bus_error=""
      last_bus_code=0
      elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
      systemd_state_log="$(sanitize_kv "${last_systemctl_state}")"
      [ -n "${systemd_state_log}" ] || systemd_state_log=unknown
      set -- \
        avahi_dbus_ready \
        outcome=ok \
        ms_elapsed="${elapsed_ms}" \
        systemd_state="${systemd_state_log}" \
        bus_status=ok
      log_info "$@"
      exit 0
    fi
    busctl_status=$?
    last_bus_code="${busctl_status}"
    bus_error_name="$(printf '%s\n' "${busctl_output}" | awk 'match($0, /org\.freedesktop\.DBus\.Error\.[A-Za-z0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"

    fallback_success=0
    fallback_hint=""
    if [ "${busctl_status}" -ne 0 ]; then
      case "${bus_error_name}" in
        org.freedesktop.DBus.Error.UnknownMethod)
          fallback_hint="unknown_method"
          ;;
      esac
      if [ -z "${fallback_hint}" ] && printf '%s' "${busctl_output}" \
        | grep -Fqi 'GetVersionString'; then
        fallback_hint="missing_get_version_string"
      fi
      if [ -n "${fallback_hint}" ]; then
        if busctl --system --timeout=2 get-property \
          org.freedesktop.Avahi \
          /org/freedesktop/Avahi/Server \
          org.freedesktop.Avahi.Server \
          State >/dev/null 2>&1; then
          fallback_success=1
          fallback_hint="get_property_state"
        elif busctl --system --timeout=2 call \
          org.freedesktop.Avahi \
          /org/freedesktop/Avahi/Server \
          org.freedesktop.Avahi.Server \
          GetState >/dev/null 2>&1; then
          fallback_success=1
          fallback_hint="call_get_state"
        fi
      fi
    fi

    if [ "${fallback_success}" -eq 1 ]; then
      last_bus_status="ok"
      last_bus_error=""
      last_bus_code=0
      elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
      systemd_state_log="$(sanitize_kv "${last_systemctl_state}")"
      [ -n "${systemd_state_log}" ] || systemd_state_log=unknown
      set -- \
        avahi_dbus_ready \
        outcome=ok \
        "ms_elapsed=${elapsed_ms}" \
        "systemd_state=${systemd_state_log}" \
        bus_status=ok
      fallback_log="$(sanitize_kv "${fallback_hint}")"
      if [ -n "${fallback_log}" ]; then
        set -- "$@" "bus_fallback=${fallback_log}"
      fi
      log_info "$@"
      exit 0
    fi

    if [ -n "${bus_error_name}" ]; then
      last_bus_error="${bus_error_name}"
      case "${bus_error_name}" in
        org.freedesktop.DBus.Error.NameHasNoOwner|org.freedesktop.DBus.Error.ServiceUnknown)
          last_bus_status="name_not_owned"
          ;;
        *)
          last_bus_status="method_error"
          ;;
      esac
    else
      last_bus_status="call_failed"
      last_bus_error="${busctl_output}"
    fi
  else
    last_bus_status="systemd_wait"
    last_bus_error=""
    last_bus_code=0
  fi

  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  if [ "${elapsed_ms}" -ge "${wait_limit_ms}" ]; then
    break
  fi

  remaining_ms=$((wait_limit_ms - elapsed_ms))
  sleep_ms="$(compute_sleep_ms "${poll_interval_ms}" "${poll_cap_ms}" "${remaining_ms}" "${jitter_fraction}")"
  if [ -z "${sleep_ms}" ]; then
    sleep_ms="${poll_interval_ms}"
  fi
  if [ "${sleep_ms}" -le 0 ]; then
    break
  fi
  sleep_secs="$(printf '%d.%03d' \
    "$((sleep_ms / 1000))" \
    "$((sleep_ms % 1000))")"
  sleep "${sleep_secs}"

  if [ "${poll_interval_ms}" -lt "${poll_cap_ms}" ]; then
    poll_interval_ms=$((poll_interval_ms * 2))
    if [ "${poll_interval_ms}" -gt "${poll_cap_ms}" ]; then
      poll_interval_ms="${poll_cap_ms}"
    fi
  fi
done

elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"

systemd_state_log="$(sanitize_kv "${last_systemctl_state}")"
[ -n "${systemd_state_log}" ] || systemd_state_log=unknown
bus_status_log="$(sanitize_kv "${last_bus_status}")"
[ -n "${bus_status_log}" ] || bus_status_log=unknown
bus_error_log="$(sanitize_kv "${last_bus_error}")"
systemd_detail_log="$(sanitize_kv "${last_systemctl_detail}")"

if [ "${systemd_absent_hint}" -ne 0 ]; then
  set -- \
    avahi_dbus_ready \
    outcome=skip \
    reason=systemd_unavailable \
    ms_elapsed="${elapsed_ms}" \
    systemd_state="${systemd_state_log}" \
    systemd_status="${last_systemctl_status}" \
    bus_status="${bus_status_log}" \
    bus_code="${last_bus_code}"
  if [ -n "${systemd_detail_log}" ]; then
    set -- "$@" systemd_detail="${systemd_detail_log}"
  fi
  if [ -n "${bus_error_log}" ]; then
    set -- "$@" bus_error="${bus_error_log}"
  fi
  log_info "$@"
  exit 2
fi

set -- \
  avahi_dbus_ready \
  outcome=timeout \
  ms_elapsed="${elapsed_ms}" \
  systemd_state="${systemd_state_log}" \
  systemd_status="${last_systemctl_status}" \
  bus_status="${bus_status_log}" \
  bus_code="${last_bus_code}"
if [ -n "${systemd_detail_log}" ]; then
  set -- "$@" systemd_detail="${systemd_detail_log}"
fi
if [ -n "${bus_error_log}" ]; then
  set -- "$@" bus_error="${bus_error_log}"
fi
log_info "$@"
exit 1
