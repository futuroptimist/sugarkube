#!/usr/bin/env bash
# mdns_ready.sh - Wrapper function to check Avahi/mDNS readiness
# Tries D-Bus first, falls back to CLI if D-Bus is unavailable
# shellcheck disable=SC3040,SC3041,SC3043
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

sanitize_kv() {
  # Match the sanitization used in wait_for_avahi_dbus.sh so log fields stay
  # consistent across scripts regardless of whitespace or locale quirks.
  LC_ALL=C printf '%s' "$1" \
    | tr '\n\r\t' '   ' \
    | tr -s ' ' ' ' \
    | tr ' ' '_' \
    | tr -cd '[:alnum:]_.:/-'
}

# Helper function to calculate elapsed milliseconds since start
elapsed_ms_since() {
  local start_ms="$1"
  python3 - <<PY
import time
start = int(${start_ms})
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
}

# mdns_ready() - Check if Avahi/mDNS is ready
#
# This function checks Avahi readiness using two methods:
# 1. D-Bus interface (primary method) - checks ownership first, then GetVersionString
# 2. avahi-browse CLI (fallback when D-Bus unavailable)
#
# Exit codes:
#   0 - Avahi is ready (via D-Bus or CLI)
#   1 - Avahi is not ready or failed
#   2 - Avahi D-Bus is disabled (enable-dbus=no in config)
#
# Environment variables:
#   AVAHI_DBUS_WAIT_MS - D-Bus ownership polling timeout in milliseconds (default: 20000)
#   AVAHI_DBUS_TIMEOUT_MS - D-Bus call timeout in milliseconds (default: 2000, max: 2000)
#   AVAHI_CONF_PATH - Path to avahi-daemon.conf (default: /etc/avahi/avahi-daemon.conf)
#   SUGARKUBE_CLUSTER - Cluster name for CLI fallback (default: sugar)
#   SUGARKUBE_ENV - Environment for CLI fallback (default: dev)
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
      elapsed_ms="$(elapsed_ms_since "${start_ms}")"
      log_info \
        mdns_ready \
        event=mdns_ready \
        outcome=disabled \
        reason=enable_dbus_no \
        method=config \
        elapsed_ms="${elapsed_ms}"
      return 2
    fi
  fi

  local dbus_wait_ms="${AVAHI_DBUS_WAIT_MS:-20000}"
  case "${dbus_wait_ms}" in
    ''|*[!0-9]*) dbus_wait_ms=20000 ;;
  esac
  if [ "${dbus_wait_ms}" -lt 0 ]; then
    dbus_wait_ms=0
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

  local method=""
  local dbus_status=0

  # Try D-Bus method first - check ownership, then GetVersionString
  if command -v busctl >/dev/null 2>&1; then
    # Poll for D-Bus ownership of org.freedesktop.Avahi with backoff
    local poll_interval_ms=200
    local poll_cap_ms=2000
    local ownership_confirmed=0
    local ownership_attempts=0
    
    while :; do
      ownership_attempts=$((ownership_attempts + 1))
      
      # Check if org.freedesktop.Avahi owns its D-Bus name
      if busctl --system call \
        org.freedesktop.DBus \
        /org/freedesktop/DBus \
        org.freedesktop.DBus \
        NameHasOwner s org.freedesktop.Avahi \
        >/dev/null 2>&1; then
        ownership_confirmed=1
        break
      fi

      # Calculate elapsed time
      local elapsed_ms
      elapsed_ms="$(elapsed_ms_since "${start_ms}")"
      
      # Check if we've exceeded the wait limit
      if [ "${elapsed_ms}" -ge "${dbus_wait_ms}" ]; then
        dbus_status=1
        break
      fi
      
      # Calculate sleep time with exponential backoff
      local remaining_ms=$((dbus_wait_ms - elapsed_ms))
      local sleep_ms="${poll_interval_ms}"
      if [ "${sleep_ms}" -gt "${remaining_ms}" ]; then
        sleep_ms="${remaining_ms}"
      fi
      if [ "${sleep_ms}" -le 0 ]; then
        break
      fi
      
      local sleep_secs
      sleep_secs="$(python3 - <<PY
sleep_ms = ${sleep_ms}
print('{:.3f}'.format(sleep_ms / 1000.0))
PY
      )"
      sleep "${sleep_secs}"
      
      # Increase poll interval with exponential backoff
      poll_interval_ms=$((poll_interval_ms * 2))
      if [ "${poll_interval_ms}" -gt "${poll_cap_ms}" ]; then
        poll_interval_ms="${poll_cap_ms}"
      fi
    done
    
    if [ "${ownership_confirmed}" -ne 1 ]; then
      local elapsed_ms
      elapsed_ms="$(elapsed_ms_since "${start_ms}")"
      log_info \
        mdns_ready \
        event=mdns_ready_dbus \
        outcome=ownership_timeout \
        method=dbus \
        elapsed_ms="${elapsed_ms}" \
        ownership_attempts="${ownership_attempts}" \
        bus_destination=org.freedesktop.DBus \
        bus_object=/org/freedesktop/DBus \
        bus_interface=org.freedesktop.DBus \
        bus_method=NameHasOwner \
        bus_owner=absent
    fi

    # If ownership confirmed, try GetVersionString
    if [ "${ownership_confirmed}" -eq 1 ]; then
      local timeout_secs=$((dbus_timeout_ms / 1000))
      [ "${timeout_secs}" -eq 0 ] && timeout_secs=1
      local bus_output=""
      if bus_output="$(busctl --system \
        --timeout="${timeout_secs}" \
        call \
        org.freedesktop.Avahi \
        /org/freedesktop/Avahi/Server \
        org.freedesktop.Avahi.Server \
        GetVersionString 2>&1)"; then
        dbus_status=0
        method="dbus"
        local elapsed_ms
        elapsed_ms="$(elapsed_ms_since "${start_ms}")"
        log_info \
          mdns_ready \
          event=mdns_ready \
          outcome=ok \
          method="${method}" \
          elapsed_ms="${elapsed_ms}" \
          ownership_attempts="${ownership_attempts}"
        return 0
      else
        dbus_status=$?
        local elapsed_ms
        elapsed_ms="$(elapsed_ms_since "${start_ms}")"
        local bus_error
        bus_error="$(sanitize_kv "${bus_output}")"
        log_info \
          mdns_ready \
          event=mdns_ready_dbus \
          outcome=call_failed \
          method=dbus \
          elapsed_ms="${elapsed_ms}" \
          ownership_attempts="${ownership_attempts}" \
          bus_destination=org.freedesktop.Avahi \
          bus_object=/org/freedesktop/Avahi/Server \
          bus_interface=org.freedesktop.Avahi.Server \
          bus_method=GetVersionString \
          bus_owner=owned \
          bus_code="${dbus_status}" \
          bus_error="${bus_error}"
      fi
    fi
  elif command -v gdbus >/dev/null 2>&1; then
    # Fallback to gdbus if busctl not available
    local dbus_timeout_secs
    dbus_timeout_secs="$(python3 - <<PY
import math
timeout_ms = ${dbus_timeout_ms}
timeout_secs = max(1, math.ceil(timeout_ms / 1000))
print(timeout_secs)
PY
    )"
    
    local gdbus_output=""
    if gdbus_output="$(gdbus call \
      --system \
      --dest org.freedesktop.Avahi \
      --object-path /org/freedesktop/Avahi/Server \
      --method org.freedesktop.Avahi.Server.GetVersionString \
      --timeout "${dbus_timeout_secs}" 2>&1)"; then
      dbus_status=0
    else
      dbus_status=$?
    fi

    if [ "${dbus_status}" -eq 0 ]; then
      method="dbus"
      local elapsed_ms
      elapsed_ms="$(elapsed_ms_since "${start_ms}")"
      log_info \
        mdns_ready \
        event=mdns_ready \
        outcome=ok \
        method="${method}" \
        elapsed_ms="${elapsed_ms}" \
        fallback=gdbus
      return 0
    else
      local elapsed_ms
      elapsed_ms="$(elapsed_ms_since "${start_ms}")"
      local bus_error
      bus_error="$(sanitize_kv "${gdbus_output}")"
      log_info \
        mdns_ready \
        event=mdns_ready_dbus \
        outcome=call_failed \
        method=dbus \
        elapsed_ms="${elapsed_ms}" \
        bus_destination=org.freedesktop.Avahi \
        bus_object=/org/freedesktop/Avahi/Server \
        bus_interface=org.freedesktop.Avahi.Server \
        bus_method=GetVersionString \
        bus_owner=unknown \
        bus_code="${dbus_status}" \
        bus_error="${bus_error}" \
        fallback=gdbus
    fi
  else
    dbus_status=127
  fi

  # D-Bus failed or unavailable, fall back to CLI method
  method="cli"
  local cli_status=0
  
  # Build service type from cluster and environment
  local cluster="${SUGARKUBE_CLUSTER:-sugar}"
  local env="${SUGARKUBE_ENV:-dev}"
  local service_type="_k3s-${cluster}-${env}._tcp"
  
  if ! command -v avahi-browse >/dev/null 2>&1; then
    local elapsed_ms
    elapsed_ms="$(elapsed_ms_since "${start_ms}")"
    log_info \
      mdns_ready \
      event=mdns_ready \
      outcome=fail \
      reason=cli_missing \
      method="${method}" \
      elapsed_ms="${elapsed_ms}" \
      dbus_status="${dbus_status}"
    return 1
  fi

  # Use timeout to prevent avahi-browse from hanging indefinitely
  # avahi-browse -t (--terminate) waits for at least one service before terminating
  # Set timeout to 5 seconds to allow enough time for service discovery
  local cli_output
  local browse_timeout=5
  if command -v timeout >/dev/null 2>&1; then
    cli_output="$(timeout "${browse_timeout}" avahi-browse -rt "${service_type}" --parsable 2>/dev/null)" || cli_status=$?
  else
    cli_output="$(avahi-browse -rt "${service_type}" --parsable 2>/dev/null)" || cli_status=$?
  fi
  
  local elapsed_ms
  elapsed_ms="$(elapsed_ms_since "${start_ms}")"

  # Check if CLI succeeded and returned actual output
  if [ "${cli_status}" -eq 0 ] && [ -n "${cli_output}" ]; then
    # avahi-browse succeeded and has output - consider mDNS ready
    log_info \
      mdns_ready \
      event=mdns_ready \
      outcome=ok \
      method="${method}" \
      elapsed_ms="${elapsed_ms}" \
      dbus_fallback=true \
      dbus_status="${dbus_status}" \
      service_type="${service_type}"
    return 0
  fi

  # Both methods failed
  local outcome="fail"
  if [ "${cli_status}" -eq 0 ] && [ -z "${cli_output}" ]; then
    outcome="timeout"  # CLI succeeded but no services found
  fi
  
  log_info \
    mdns_ready \
    event=mdns_ready \
    outcome="${outcome}" \
    method="${method}" \
    elapsed_ms="${elapsed_ms}" \
    dbus_status="${dbus_status}" \
    cli_status="${cli_status}" \
    service_type="${service_type}"
  return 1
}

# If script is run directly (not sourced), execute mdns_ready
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  mdns_ready
fi
