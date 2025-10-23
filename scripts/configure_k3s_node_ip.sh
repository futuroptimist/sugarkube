#!/usr/bin/env bash
set -euo pipefail

select_primary_ipv4() {
  awk '
    $3 == "inet" {
      split($4, addr, "/")
      if (addr[1] != "") {
        print addr[1]
        exit
      }
    }
  '
}

if [[ "${1:-}" == "--detect-ip-from-stdin" ]]; then
  select_primary_ipv4
  exit 0
fi

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_k3s_node_ip.log"

mkdir -p "${LOG_DIR}"

log() {
  local ts
  ts="$(date +'%Y-%m-%dT%H:%M:%S%z')"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}"
}

log "Resolving primary IPv4 for ${IFACE}"

ip_output=""
if [ -n "${SUGARKUBE_IP_MOCK_DATA:-}" ]; then
  ip_output="${SUGARKUBE_IP_MOCK_DATA}"
else
  if ! command -v ip >/dev/null 2>&1; then
    log "ip command not available"
    exit 1
  fi
  ip_output="$(ip -4 -o addr show "${IFACE}" 2>/dev/null || true)"
fi

if [ -z "${ip_output}" ]; then
  log "No IPv4 addresses reported for ${IFACE}"
  exit 1
fi

PRIMARY_IP="$(printf '%s\n' "${ip_output}" | select_primary_ipv4 || true)"
if [ -z "${PRIMARY_IP}" ]; then
  log "Failed to parse IPv4 address for ${IFACE}"
  exit 1
fi

log "Detected IPv4 ${PRIMARY_IP} on ${IFACE}"

update_dropin() {
  local service="$1"
  local unit_dir="/etc/systemd/system/${service}.d"
  local dropin_file="${unit_dir}/10-node-ip.conf"
  local tmp
  tmp="$(mktemp)"
  printf '[Service]\nEnvironment=K3S_NODE_IP=%s\n' "${PRIMARY_IP}" >"${tmp}"
  mkdir -p "${unit_dir}"
  if [ -f "${dropin_file}" ] && cmp -s "${dropin_file}" "${tmp}"; then
    rm -f "${tmp}"
    return 1
  fi
  cat "${tmp}" >"${dropin_file}"
  rm -f "${tmp}"
  return 0
}

declare -a services=()
if command -v systemctl >/dev/null 2>&1; then
  unit_files="$(systemctl list-unit-files | awk '{print $1}' || true)"
  if printf '%s\n' "${unit_files}" | grep -qx 'k3s.service'; then
    services+=("k3s.service")
  fi
  if printf '%s\n' "${unit_files}" | grep -qx 'k3s-agent.service'; then
    services+=("k3s-agent.service")
  fi
else
  for candidate in k3s.service k3s-agent.service; do
    if [ -f "/etc/systemd/system/${candidate}" ] || \
       [ -f "/lib/systemd/system/${candidate}" ] || \
       [ -d "/etc/systemd/system/${candidate}.d" ]; then
      services+=("${candidate}")
    fi
  done
fi

if [ ${#services[@]} -eq 0 ]; then
  services=("k3s.service")
fi

declare -a updated_services=()
any_updated=0
for svc in "${services[@]}"; do
  if update_dropin "${svc}"; then
    log "Updated ${svc} drop-in with K3S_NODE_IP=${PRIMARY_IP}"
    updated_services+=("${svc}")
    any_updated=1
  else
    log "Drop-in for ${svc} already set to ${PRIMARY_IP}"
  fi
done

if [ "${any_updated}" -eq 1 ]; then
  if [ "${K3S_SKIP_SYSTEMCTL:-0}" = "1" ]; then
    log "K3S_SKIP_SYSTEMCTL=1; skipping daemon-reload"
  elif command -v systemctl >/dev/null 2>&1; then
    log "Reloading systemd manager configuration"
    systemctl daemon-reload
    for svc in "${updated_services[@]}"; do
      if systemctl is-active --quiet "${svc}"; then
        log "Restarting ${svc} to apply node IP"
        systemctl restart "${svc}"
      else
        log "${svc} is not active; skipping restart"
      fi
    done
  else
    log "systemctl not available; skipping reload and restart"
  fi
else
  log "All drop-ins already configured; no reload required"
fi

log "configure_k3s_node_ip.sh completed"
