#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
IPV4_ONLY="${SUGARKUBE_MDNS_IPV4_ONLY:-1}"
CONF="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
BACKUP_PATH="${CONF}.bak"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_avahi.log"
if [ -z "${SYSTEMCTL_BIN+x}" ]; then
  SYSTEMCTL_BIN="systemctl"
fi

mkdir -p "${LOG_DIR}"

log() {
  local timestamp
  timestamp="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf '%s %s\n' "${timestamp}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

ensure_conf_exists() {
  local conf_dir
  conf_dir="$(dirname "${CONF}")"
  if [ ! -d "${conf_dir}" ]; then
    mkdir -p "${conf_dir}"
    log "Created directory ${conf_dir}"
  fi
  if [ ! -e "${CONF}" ]; then
    : >"${CONF}"
    log "Created empty ${CONF}"
  fi
}

backup_conf() {
  if [ -f "${BACKUP_PATH}" ]; then
    return
  fi
  if [ -f "${CONF}" ]; then
    cp "${CONF}" "${BACKUP_PATH}"
    log "Backed up ${CONF} to ${BACKUP_PATH}"
  fi
}

render_config() {
  awk -v iface="${IFACE}" -v ipv4_only="${IPV4_ONLY}" '
    function flush_server() {
      if (in_server) {
        if (allow_written == 0) {
          print "allow-interfaces=" iface
          allow_written = 1
          last_line_blank = 0
        }
        if (ipv4_only == "1") {
          if (use_ipv4_written == 0) {
            print "use-ipv4=yes"
            use_ipv4_written = 1
            last_line_blank = 0
          }
          if (use_ipv6_written == 0) {
            print "use-ipv6=no"
            use_ipv6_written = 1
            last_line_blank = 0
          }
        }
      }
    }
    BEGIN {
      in_server = 0
      found_server = 0
      allow_written = 0
      use_ipv4_written = 0
      use_ipv6_written = 0
      last_line_blank = 1
    }
    /^[[:space:]]*\[.*\][[:space:]]*$/ {
      if (in_server) {
        flush_server()
      }
      in_server = ($0 ~ /^[[:space:]]*\[server\][[:space:]]*$/)
      if (in_server) {
        found_server = 1
        allow_written = 0
        use_ipv4_written = 0
        use_ipv6_written = 0
      }
      print $0
      last_line_blank = ($0 ~ /^[[:space:]]*$/)
      next
    }
    {
      if (in_server) {
        if ($0 ~ /^[[:space:]]*allow-interfaces[[:space:]]*=/) {
          print "allow-interfaces=" iface
          allow_written = 1
          last_line_blank = 0
          next
        }
        if (ipv4_only == "1" && $0 ~ /^[[:space:]]*use-ipv4[[:space:]]*=/) {
          print "use-ipv4=yes"
          use_ipv4_written = 1
          last_line_blank = 0
          next
        }
        if (ipv4_only == "1" && $0 ~ /^[[:space:]]*use-ipv6[[:space:]]*=/) {
          print "use-ipv6=no"
          use_ipv6_written = 1
          last_line_blank = 0
          next
        }
      }
      print $0
      last_line_blank = ($0 ~ /^[[:space:]]*$/)
    }
    END {
      if (in_server) {
        flush_server()
      }
      if (found_server == 0) {
        if (NR > 0 && last_line_blank == 0) {
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
  ' "${CONF}"
}

replace_if_changed() {
  local tmp new_path mode owner group
  tmp="$(mktemp)"
  new_path="${CONF}.sugarkube.$$"
  trap 'rm -f "${tmp}" "${new_path}"' EXIT
  render_config >"${tmp}"
  if [ -f "${CONF}" ] && cmp -s "${tmp}" "${CONF}"; then
    rm -f "${tmp}"
    trap - EXIT
    log "${CONF} already configured for ${IFACE}"
    return 1
  fi
  mode=644
  owner=0
  group=0
  if [ -e "${CONF}" ]; then
    mode="$(stat -c '%a' "${CONF}")"
    owner="$(stat -c '%u' "${CONF}")"
    group="$(stat -c '%g' "${CONF}")"
  fi
  install -m "${mode}" "${tmp}" "${new_path}"
  chown "${owner}:${group}" "${new_path}"
  mv "${new_path}" "${CONF}"
  rm -f "${tmp}"
  trap - EXIT
  log "Updated ${CONF} for interface ${IFACE}"
  return 0
}

restart_avahi() {
  if [ "${SYSTEMCTL_BIN}" = "" ]; then
    log "SYSTEMCTL_BIN unset; skipping avahi-daemon restart"
    return
  fi
  if ! command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    log "${SYSTEMCTL_BIN} not available; skipping avahi-daemon restart"
    return
  fi
  if "${SYSTEMCTL_BIN}" is-active --quiet avahi-daemon; then
    "${SYSTEMCTL_BIN}" restart avahi-daemon
    log "Restarted avahi-daemon"
  else
    log "avahi-daemon inactive; skipping restart"
  fi
}

log "Configuring Avahi to use ${IFACE} (IPv4 only=${IPV4_ONLY})"
ensure_conf_exists
backup_conf
if replace_if_changed; then
  restart_avahi
else
  log "No Avahi restart required"
fi
