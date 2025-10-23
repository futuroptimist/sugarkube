#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
IPV4_ONLY="${SUGARKUBE_MDNS_IPV4_ONLY:-1}"
CONF="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
BACKUP="${CONF}.bak"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_avahi.log"

log() {
  local timestamp
  timestamp="$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  local message="$*"
  printf '%s %s\n' "${timestamp}" "${message}"
  printf '%s %s\n' "${timestamp}" "${message}" >>"${LOG_FILE}"
}

render_config() {
  local dest="$1"
  if [ ! -f "${CONF}" ]; then
    {
      printf '[server]\n'
      printf 'allow-interfaces=%s\n' "${IFACE}"
      if [ "${IPV4_ONLY}" = "1" ]; then
        printf 'use-ipv4=yes\n'
        printf 'use-ipv6=no\n'
      fi
    } >"${dest}"
    return 0
  fi

  awk -v iface="${IFACE}" -v ipv4_only="${IPV4_ONLY}" '
  function flush_server() {
    if (in_server == 0) {
      return
    }
    if (!allow_written) {
      print "allow-interfaces=" iface
    }
    if (ipv4_only == "1") {
      if (!ipv4_written) {
        print "use-ipv4=yes"
      }
      if (!ipv6_written) {
        print "use-ipv6=no"
      }
    }
    in_server = 0
  }
  BEGIN {
    server_seen = 0
    in_server = 0
    allow_written = 0
    ipv4_written = 0
    ipv6_written = 0
  }
  {
    if ($0 ~ /^\[server\]/) {
      flush_server()
      server_seen = 1
      in_server = 1
      allow_written = 0
      ipv4_written = 0
      ipv6_written = 0
      print $0
      next
    }
    if (in_server && $0 ~ /^\[/) {
      flush_server()
    }
    if (in_server) {
      if ($0 ~ /^allow-interfaces=/) {
        print "allow-interfaces=" iface
        allow_written = 1
      } else if ($0 ~ /^use-ipv4=/) {
        if (ipv4_only == "1") {
          print "use-ipv4=yes"
        } else {
          print $0
        }
        ipv4_written = 1
      } else if ($0 ~ /^use-ipv6=/) {
        if (ipv4_only == "1") {
          print "use-ipv6=no"
        } else {
          print $0
        }
        ipv6_written = 1
      } else {
        print $0
      }
      next
    }
    print $0
  }
  END {
    if (in_server) {
      flush_server()
    }
    if (!server_seen) {
      if (NR > 0) {
        print ""
      }
      print "[server]"
      print "allow-interfaces=" iface
      if (ipv4_only == "1") {
        print "use-ipv4=yes"
        print "use-ipv6=no"
      }
    }
  }
  ' "${CONF}" >"${dest}"
}

main() {
  mkdir -p "${LOG_DIR}"
  touch "${LOG_FILE}"
  log "Starting Avahi configuration: interface=${IFACE} ipv4_only=${IPV4_ONLY}"

  if [ ! -f "${CONF}" ]; then
    log "Configuration file not found: ${CONF}"
    exit 1
  fi

  if [ ! -f "${BACKUP}" ]; then
    cp "${CONF}" "${BACKUP}"
    log "Created backup at ${BACKUP}"
  else
    log "Backup already exists at ${BACKUP}"
  fi

  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "${tmp}"' EXIT

  render_config "${tmp}"

  local changed=0
  if ! cmp -s "${tmp}" "${CONF}"; then
    changed=1
    local mode owner group
    mode="$(stat -c '%a' "${CONF}" 2>/dev/null || echo '0644')"
    owner="$(stat -c '%u' "${CONF}" 2>/dev/null || echo '0')"
    group="$(stat -c '%g' "${CONF}" 2>/dev/null || echo '0')"
    install -o "${owner}" -g "${group}" -m "${mode}" "${tmp}" "${CONF}"
    log "Updated ${CONF}"
  else
    log "No changes required for ${CONF}"
  fi

  rm -f "${tmp}"
  trap - EXIT

  if [ "${changed}" -eq 1 ]; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
      log "Restarting avahi-daemon"
      systemctl restart avahi-daemon
      log "avahi-daemon restarted"
    else
      log "systemctl unavailable; skipping avahi-daemon restart"
    fi
  else
    log "Skipping avahi-daemon restart"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
