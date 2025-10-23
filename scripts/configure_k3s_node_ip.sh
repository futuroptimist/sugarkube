#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
IP_CMD="${IP_CMD:-ip}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN-systemctl}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_k3s_node_ip.log"
SYSTEMD_SYSTEM_DIR="${SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}"
UNIT_SEARCH_PATHS="${SYSTEMD_UNIT_PATHS:-/etc/systemd/system:/lib/systemd/system:/usr/lib/systemd/system}"
DROPIN_NAME="10-node-ip.conf"

log() {
  local ts
  ts="$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  mkdir -p "${LOG_DIR}"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

select_primary_ipv4_from_ip_output() {
  awk '
    $3 == "inet" {
      split($4, addr, "/")
      if (addr[1] != "") {
        print addr[1]
        exit 0
      }
    }
  '
}

unit_exists() {
  local unit="$1"
  IFS=':' read -r -a search_paths <<<"${UNIT_SEARCH_PATHS}"
  for dir in "${search_paths[@]}"; do
    if [ -e "${dir}/${unit}" ]; then
      return 0
    fi
  done
  if [ -n "${SYSTEMCTL_BIN}" ] && command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    if "${SYSTEMCTL_BIN}" list-unit-files "${unit}" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

write_dropin() {
  local unit="$1"
  local ip="$2"
  local dir file tmp mode owner group
  dir="${SYSTEMD_SYSTEM_DIR}/${unit}.d"
  file="${dir}/${DROPIN_NAME}"
  mkdir -p "${dir}"
  tmp="$(mktemp "${dir}/${DROPIN_NAME}.XXXXXX")"

  mode="0644"
  owner=""
  group=""
  if [ -e "${file}" ]; then
    mode="$(stat -c '%a' "${file}" 2>/dev/null || echo '0644')"
    owner="$(stat -c '%u' "${file}" 2>/dev/null || echo '')"
    group="$(stat -c '%g' "${file}" 2>/dev/null || echo '')"
  fi

  {
    printf '[Service]\n'
    printf 'Environment=K3S_NODE_IP=%s\n' "${ip}"
  } >"${tmp}"

  chmod "${mode}" "${tmp}"
  if [ -n "${owner}" ] && [ -n "${group}" ]; then
    chown "${owner}:${group}" "${tmp}" || true
  fi

  local changed=1
  if [ -f "${file}" ] && cmp -s "${tmp}" "${file}"; then
    changed=0
  fi

  if [ "${changed}" -eq 1 ]; then
    log "Writing drop-in for ${unit} with IP ${ip}"
    mv "${tmp}" "${file}"
    return 0
  fi

  rm -f "${tmp}"
  return 1
}

detect_primary_ipv4() {
  local output
  if ! command -v "${IP_CMD}" >/dev/null 2>&1; then
    log "${IP_CMD} command not available"
    return 1
  fi
  output="$(${IP_CMD} -4 -o addr show "${IFACE}" 2>/dev/null || true)"
  if [ -z "${output}" ]; then
    log "No IPv4 addresses detected on ${IFACE}"
    return 1
  fi
  local ip
  ip="$(printf '%s\n' "${output}" | select_primary_ipv4_from_ip_output)"
  if [ -z "${ip}" ]; then
    log "Failed to parse IPv4 address for ${IFACE}"
    return 1
  fi
  printf '%s\n' "${ip}"
}

restart_services_if_needed() {
  local -a services=("$@")
  if [ ${#services[@]} -eq 0 ]; then
    return
  fi
  if [ -z "${SYSTEMCTL_BIN}" ] || ! command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    log "systemctl unavailable; skipping daemon-reload and restarts"
    return
  fi
  log "Reloading systemd daemon"
  "${SYSTEMCTL_BIN}" daemon-reload
  local svc
  for svc in "${services[@]}"; do
    if "${SYSTEMCTL_BIN}" is-active --quiet "${svc}"; then
      log "Restarting ${svc} to apply node IP"
      "${SYSTEMCTL_BIN}" restart "${svc}"
    else
      log "${svc} not active; skipping restart"
    fi
  done
}

main() {
  log "Configuring k3s node IP via ${IFACE}"
  local ip
  ip="$(detect_primary_ipv4)" || {
    log "Unable to detect IPv4 on ${IFACE}";
    exit 1;
  }
  log "Detected IPv4 ${ip} on ${IFACE}"

  local -a changed_services=()
  local unit
  for unit in k3s.service k3s-agent.service; do
    if unit_exists "${unit}"; then
      if write_dropin "${unit}" "${ip}"; then
        changed_services+=("${unit}")
      else
        log "Drop-in for ${unit} already up-to-date"
      fi
    else
      log "Unit ${unit} not found; skipping"
    fi
  done

  restart_services_if_needed "${changed_services[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
