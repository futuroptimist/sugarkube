#!/usr/bin/env bash
# mdns_ready.sh - Wrapper function to check Avahi/mDNS readiness
# Tries D-Bus first, falls back to CLI if D-Bus is unavailable
# shellcheck disable=SC3040,SC3041,SC3043
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

# mdns_ready() - Check if Avahi/mDNS is ready
#
# This function checks Avahi readiness using two methods:
# 1. D-Bus interface (primary method)
# 2. avahi-browse CLI (fallback when D-Bus unavailable)
#
# Exit codes:
#   0 - Avahi is ready (via D-Bus or CLI)
#   1 - Avahi is not ready or failed
#   2 - Avahi D-Bus is disabled (enable-dbus=no in config)
#
# Environment variables:
#   AVAHI_DBUS_TIMEOUT_MS - D-Bus call timeout in milliseconds (default: 2000, max: 2000)
#   AVAHI_CONF_PATH - Path to avahi-daemon.conf (default: /etc/avahi/avahi-daemon.conf)
mdns_ready() {
  local start_ms
  start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
  )"

  local avahi_conf_path="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
  
  # Check if D-Bus is disabled in Avahi configuration
  if [ -f "${avahi_conf_path}" ]; then
    if LC_ALL=C grep -Eiq '^[[:space:]]*enable-dbus[[:space:]]*=[[:space:]]*no([[:space:]]|$)' \
      "${avahi_conf_path}"; then
      local elapsed_ms
      elapsed_ms="$(python3 - <<PY
import time
start = int(${start_ms})
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
      )"
      log_info \
        mdns_ready \
        outcome=disabled \
        reason=enable_dbus_no \
        method=config \
        elapsed_ms="${elapsed_ms}"
      return 2
    fi
  fi

  local dbus_timeout_ms="${AVAHI_DBUS_TIMEOUT_MS:-2000}"
  case "${dbus_timeout_ms}" in
    ''|*[!0-9]*) dbus_timeout_ms=2000 ;;
  esac
  if [ "${dbus_timeout_ms}" -lt 100 ]; then
    dbus_timeout_ms=100
  elif [ "${dbus_timeout_ms}" -gt 2000 ]; then
    dbus_timeout_ms=2000
  fi
  
  local dbus_timeout_secs
  dbus_timeout_secs="$(python3 - <<PY
timeout_ms = ${dbus_timeout_ms}
timeout_secs = max(1, int(timeout_ms / 1000))
print(timeout_secs)
PY
  )"

  local method=""
  local dbus_status=0
  local dbus_output=""
  local dbus_cmd=""

  # Try D-Bus method first
  if command -v gdbus >/dev/null 2>&1; then
    dbus_cmd="gdbus call --system --dest org.freedesktop.Avahi --object-path / --method org.freedesktop.Avahi.Server.GetVersionString"
    dbus_output="$(gdbus call \
      --system \
      --dest org.freedesktop.Avahi \
      --object-path / \
      --method org.freedesktop.Avahi.Server.GetVersionString \
      --timeout "${dbus_timeout_secs}" \
      2>&1)" || dbus_status=$?
    
    if [ "${dbus_status}" -eq 0 ]; then
      method="dbus"
      local elapsed_ms
      elapsed_ms="$(python3 - <<PY
import time
start = int(${start_ms})
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
      )"
      log_info \
        mdns_ready \
        outcome=ok \
        method="${method}" \
        elapsed_ms="${elapsed_ms}" \
        timeout_ms="${dbus_timeout_ms}"
      return 0
    fi
  else
    dbus_status=127
    dbus_output="gdbus command not found"
  fi

  # D-Bus failed or unavailable, fall back to CLI method
  method="cli"
  local cli_status=0
  local cli_output=""
  local browse_cmd="avahi-browse --all --ignore-local --resolve --terminate"
  
  if ! command -v avahi-browse >/dev/null 2>&1; then
    local elapsed_ms
    elapsed_ms="$(python3 - <<PY
import time
start = int(${start_ms})
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
    )"
    log_info \
      mdns_ready \
      outcome=fail \
      reason=cli_missing \
      method="${method}" \
      elapsed_ms="${elapsed_ms}" \
      dbus_status="${dbus_status}"
    return 1
  fi

  cli_output="$(avahi-browse --all --ignore-local --resolve --terminate 2>&1)" || cli_status=$?
  
  local elapsed_ms
  elapsed_ms="$(python3 - <<PY
import time
start = int(${start_ms})
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
  )"

  if [ "${cli_status}" -eq 0 ]; then
    log_info \
      mdns_ready \
      outcome=ok \
      method="${method}" \
      elapsed_ms="${elapsed_ms}" \
      dbus_fallback=true \
      dbus_status="${dbus_status}" \
      browse_command="${browse_cmd}"
    return 0
  fi

  # Both methods failed
  log_info \
    mdns_ready \
    outcome=fail \
    method="${method}" \
    elapsed_ms="${elapsed_ms}" \
    dbus_status="${dbus_status}" \
    cli_status="${cli_status}" \
    browse_command="${browse_cmd}"
  return 1
}

# If script is run directly (not sourced), execute mdns_ready
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  mdns_ready
fi
