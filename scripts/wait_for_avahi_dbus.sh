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

if ! command -v gdbus >/dev/null 2>&1; then
  log_info avahi_dbus_ready outcome=skip reason=gdbus_missing
  exit 2
fi

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

poll_interval_ms=100
poll_cap_ms=500

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

  if gdbus introspect \
    --system \
    --dest org.freedesktop.Avahi \
    --object-path /org/freedesktop/Avahi/Server \
    --timeout 1 >/dev/null 2>&1; then
    elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
    log_info avahi_dbus_ready outcome=ok ms_elapsed="${elapsed_ms}"
    exit 0
  fi

  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  if [ "${elapsed_ms}" -ge "${wait_limit_ms}" ]; then
    break
  fi

  sleep_secs="$(printf '%d.%03d' \
    "$((poll_interval_ms / 1000))" \
    "$((poll_interval_ms % 1000))")"
  sleep "${sleep_secs}"

  if [ "${poll_interval_ms}" -lt "${poll_cap_ms}" ]; then
    poll_interval_ms=$((poll_interval_ms * 2))
    if [ "${poll_interval_ms}" -gt "${poll_cap_ms}" ]; then
      poll_interval_ms="${poll_cap_ms}"
    fi
  fi
done

elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"

if dbus_disabled; then
  log_info \
    avahi_dbus_ready \
    outcome=disabled \
    reason=enable_dbus_no \
    severity=info \
    ms_elapsed="${elapsed_ms}"
  exit 2
fi

busctl_state="unknown"
dbus_ping="skipped"

if command -v busctl >/dev/null 2>&1; then
  busctl_output=""
  if busctl_output="$(busctl --system list 2>/dev/null)"; then
    if printf '%s\n' "${busctl_output}" | grep -F "org.freedesktop.Avahi" >/dev/null 2>&1; then
      busctl_state="present"
    else
      busctl_state="absent"
      if gdbus introspect \
        --system \
        --dest org.freedesktop.DBus \
        --object-path /org/freedesktop/DBus \
        --timeout 1 >/dev/null 2>&1; then
        dbus_ping="ok"
      else
        dbus_ping="error"
      fi
    fi
  else
    busctl_state="error"
  fi
else
  busctl_state="missing"
fi

log_info \
  avahi_dbus_ready \
  outcome=timeout \
  ms_elapsed="${elapsed_ms}" \
  busctl="${busctl_state}" \
  dbus_ping="${dbus_ping}"
exit 1
