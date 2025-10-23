#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
IPV4_ONLY="${SUGARKUBE_MDNS_IPV4_ONLY:-1}"
CONF_PATH="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_avahi.log"

mkdir -p "${LOG_DIR}"

log() {
  local ts
  ts="$(date +'%Y-%m-%dT%H:%M:%S%z')"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}"
}

if [ ! -f "${CONF_PATH}" ]; then
  log "Avahi configuration not found at ${CONF_PATH}"
  exit 1
fi

if [ ! -f "${CONF_PATH}.bak" ]; then
  cp "${CONF_PATH}" "${CONF_PATH}.bak"
  log "Backed up ${CONF_PATH} to ${CONF_PATH}.bak"
fi

tmp_file="$(mktemp)"
cleanup() {
  rm -f "${tmp_file}"
}
trap cleanup EXIT

awk -v iface="${IFACE}" -v ipv4_only="${IPV4_ONLY}" '
function flush_server() {
  if (!inside_server) {
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
}
BEGIN {
  inside_server = 0
  seen_server = 0
  allow_written = 0
  ipv4_written = 0
  ipv6_written = 0
}
/^[ \t]*\[.*\][ \t]*$/ {
  if (inside_server) {
    flush_server()
  }
  print
  if ($0 ~ /^[ \t]*\[server\][ \t]*$/) {
    inside_server = 1
    seen_server = 1
    allow_written = 0
    ipv4_written = 0
    ipv6_written = 0
  } else {
    inside_server = 0
  }
  next
}
{
  if (inside_server) {
    if ($0 ~ /^[ \t]*allow-interfaces[ \t]*=/) {
      print "allow-interfaces=" iface
      allow_written = 1
      next
    }
    if (ipv4_only == "1" && $0 ~ /^[ \t]*use-ipv4[ \t]*=/) {
      print "use-ipv4=yes"
      ipv4_written = 1
      next
    }
    if (ipv4_only == "1" && $0 ~ /^[ \t]*use-ipv6[ \t]*=/) {
      print "use-ipv6=no"
      ipv6_written = 1
      next
    }
  }
  print
}
END {
  if (inside_server) {
    flush_server()
  } else if (!seen_server) {
    if (NR > 0 && $0 !~ /^[ \t]*$/) {
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
' "${CONF_PATH}" >"${tmp_file}"

changed=0
if cmp -s "${CONF_PATH}" "${tmp_file}"; then
  log "No changes required for ${CONF_PATH}"
else
  cat "${tmp_file}" >"${CONF_PATH}"
  changed=1
  log "Updated ${CONF_PATH} with allow-interfaces=${IFACE}"
  if [ "${IPV4_ONLY}" = "1" ]; then
    log "Pinned Avahi to IPv4 on ${IFACE}"
  fi
fi

if [ "${changed}" -eq 1 ]; then
  if [ "${AVAHI_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    log "AVAHI_SKIP_SYSTEMCTL=1; skipping avahi-daemon restart"
  elif command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet avahi-daemon; then
      log "Restarting avahi-daemon"
      systemctl restart avahi-daemon
    else
      log "avahi-daemon is not active; skipping restart"
    fi
  else
    log "systemctl not found; skipping avahi-daemon restart"
  fi
fi

log "configure_avahi.sh completed"
