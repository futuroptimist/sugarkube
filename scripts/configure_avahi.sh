#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
IPV4_ONLY="${SUGARKUBE_MDNS_IPV4_ONLY:-1}"
CONF="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN-systemctl}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_avahi.log"

log() {
  local ts
  ts="$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  mkdir -p "${LOG_DIR}"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

ensure_config_exists() {
  local dir
  dir="$(dirname "${CONF}")"
  if [ ! -d "${dir}" ]; then
    log "Creating directory ${dir}"
    mkdir -p "${dir}"
  fi
  if [ ! -e "${CONF}" ]; then
    log "Creating new Avahi configuration at ${CONF}"
    touch "${CONF}"
  fi
}

backup_config() {
  local backup
  backup="${CONF}.bak"
  if [ ! -e "${backup}" ]; then
    log "Backing up ${CONF} to ${backup}"
    cp "${CONF}" "${backup}"
  else
    log "Backup ${backup} already present; skipping"
  fi
}

render_config() {
  local tmp mode owner group
  local dir
  dir="$(dirname "${CONF}")"
  tmp="$(mktemp "${dir}/avahi-daemon.conf.XXXXXX")"
  mode=""
  owner=""
  group=""
  if [ -e "${CONF}" ]; then
    mode="$(stat -c '%a' "${CONF}" 2>/dev/null || echo '')"
    owner="$(stat -c '%u' "${CONF}" 2>/dev/null || echo '')"
    group="$(stat -c '%g' "${CONF}" 2>/dev/null || echo '')"
  fi

  awk -v iface="${IFACE}" -v ipv4_only="${IPV4_ONLY}" '
    function flush_server() {
      if (in_server) {
        if (!allow_written) {
          print "allow-interfaces=" iface
        }
        if (ipv4_only == "1") {
          if (!use_ipv4_written) {
            print "use-ipv4=yes"
          }
          if (!use_ipv6_written) {
            print "use-ipv6=no"
          }
        }
        in_server = 0
      }
    }
    {
      if ($0 ~ /^\[[[:space:]]*server[[:space:]]*\]/) {
        flush_server()
        in_server = 1
        server_seen = 1
        allow_written = 0
        use_ipv4_written = 0
        use_ipv6_written = 0
        print "[server]"
        next
      } else if ($0 ~ /^\[.*\]/) {
        flush_server()
        print $0
        next
      }

      if (in_server) {
        if ($0 ~ /^allow-interfaces[[:space:]]*=/) {
          print "allow-interfaces=" iface
          allow_written = 1
          next
        }
        if (ipv4_only == "1" && $0 ~ /^use-ipv4[[:space:]]*=/) {
          print "use-ipv4=yes"
          use_ipv4_written = 1
          next
        }
        if (ipv4_only == "1" && $0 ~ /^use-ipv6[[:space:]]*=/) {
          print "use-ipv6=no"
          use_ipv6_written = 1
          next
        }
      }
      print $0
    }
    END {
      if (in_server) {
        if (!allow_written) {
          print "allow-interfaces=" iface
        }
        if (ipv4_only == "1") {
          if (!use_ipv4_written) {
            print "use-ipv4=yes"
          }
          if (!use_ipv6_written) {
            print "use-ipv6=no"
          }
        }
      }
      if (!server_seen) {
        if (NR > 0 && $0 !~ /^$/) {
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
  ' "${CONF}" >"${tmp}"

  if [ -n "${mode}" ]; then
    chmod "${mode}" "${tmp}"
  else
    chmod 0644 "${tmp}"
  fi
  if [ -n "${owner}" ] && [ -n "${group}" ]; then
    chown "${owner}:${group}" "${tmp}" || true
  fi

  printf '%s' "${tmp}"
}

restart_avahi_if_needed() {
  if [ -z "${SYSTEMCTL_BIN}" ]; then
    log "SYSTEMCTL_BIN unset; skipping avahi-daemon restart"
    return
  fi
  if ! command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    log "${SYSTEMCTL_BIN} not available; skipping avahi-daemon restart"
    return
  fi
  if "${SYSTEMCTL_BIN}" is-active --quiet avahi-daemon; then
    log "Restarting avahi-daemon"
    "${SYSTEMCTL_BIN}" restart avahi-daemon
  else
    log "avahi-daemon not active; skipping restart"
  fi
}

main() {
  log "Configuring Avahi to use interface ${IFACE} (IPv4 only=${IPV4_ONLY})"
  ensure_config_exists
  backup_config

  local tmp
  tmp="$(render_config)"
  trap 'rm -f "${tmp}"' EXIT

  if [ -f "${CONF}" ] && cmp -s "${tmp}" "${CONF}"; then
    log "No changes required for ${CONF}"
    rm -f "${tmp}"
    trap - EXIT
    return
  fi

  log "Updating ${CONF}"
  mv "${tmp}" "${CONF}"
  trap - EXIT
  restart_avahi_if_needed
}

main "$@"
