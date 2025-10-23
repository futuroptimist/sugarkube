#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_k3s_node_ip.log"
DROPIN_NAME="10-node-ip.conf"

log() {
  local timestamp
  timestamp="$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  local message="$*"
  printf '%s %s\n' "${timestamp}" "${message}"
  printf '%s %s\n' "${timestamp}" "${message}" >>"${LOG_FILE}"
}

extract_primary_ipv4() {
  local line candidate
  while IFS= read -r line; do
    case "${line}" in
      *" inet "*)
        candidate="${line#* inet }"
        candidate="${candidate%% *}"
        if [[ "${candidate}" == */* ]]; then
          printf '%s\n' "${candidate%%/*}"
          return 0
        fi
        ;;
    esac
  done
  return 1
}

service_exists() {
  local svc="$1"
  if systemctl list-unit-files "${svc}" >/dev/null 2>&1; then
    return 0
  fi
  if systemctl status "${svc}" >/dev/null 2>&1; then
    return 0
  fi
  if [ -f "/etc/systemd/system/${svc}" ] || [ -f "/lib/systemd/system/${svc}" ]; then
    return 0
  fi
  return 1
}

write_dropin() {
  local svc="$1"
  local ip="$2"
  local dir="/etc/systemd/system/${svc}.d"
  local path="${dir}/${DROPIN_NAME}"
  local tmp

  mkdir -p "${dir}"
  tmp="$(mktemp)"
  {
    printf '[Service]\n'
    printf 'Environment=K3S_NODE_IP=%s\n' "${ip}"
  } >"${tmp}"

  if [ -f "${path}" ] && cmp -s "${tmp}" "${path}"; then
    rm -f "${tmp}"
    return 1
  fi

  local mode owner group
  if [ -f "${path}" ]; then
    mode="$(stat -c '%a' "${path}" 2>/dev/null || echo '0644')"
    owner="$(stat -c '%u' "${path}" 2>/dev/null || echo '0')"
    group="$(stat -c '%g' "${path}" 2>/dev/null || echo '0')"
  else
    mode='0644'
    owner='0'
    group='0'
  fi

  install -o "${owner}" -g "${group}" -m "${mode}" "${tmp}" "${path}"
  rm -f "${tmp}"
  return 0
}

main() {
  mkdir -p "${LOG_DIR}"
  touch "${LOG_FILE}"
  log "Starting k3s node IP configuration for interface ${IFACE}"

  local ip_output ip_addr
  if ! ip_output="$(ip -4 -o addr show "${IFACE}" 2>/dev/null)"; then
    log "Failed to query IPv4 address on ${IFACE}"
    exit 1
  fi

  if ! ip_addr="$(printf '%s\n' "${ip_output}" | extract_primary_ipv4)"; then
    log "No IPv4 address detected on ${IFACE}"
    exit 1
  fi

  log "Detected IPv4 address ${ip_addr} on ${IFACE}"

  local reload_needed=0
  local -a restart_services=()
  local svc
  for svc in k3s.service k3s-agent.service; do
    if ! service_exists "${svc}"; then
      log "${svc} not found; skipping drop-in"
      continue
    fi

    if write_dropin "${svc}" "${ip_addr}"; then
      log "Updated ${svc} drop-in with K3S_NODE_IP=${ip_addr}"
      reload_needed=1
      restart_services+=("${svc}")
    else
      log "${svc} drop-in already up to date"
    fi
  done

  if [ "${reload_needed}" -eq 1 ]; then
    systemctl daemon-reload
    log "Reloaded systemd units"
    local unit
    for unit in "${restart_services[@]}"; do
      if systemctl is-active --quiet "${unit}"; then
        systemctl restart "${unit}"
        log "Restarted ${unit}"
      else
        log "${unit} not active; skipping restart"
      fi
    done
  else
    log "No changes detected; skipping daemon-reload"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
