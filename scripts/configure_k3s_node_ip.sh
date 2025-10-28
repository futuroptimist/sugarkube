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
K3S_CONFIG_DIR="${K3S_CONFIG_DIR:-/etc/rancher/k3s}"
TLS_SAN_TEMPLATE_PATH="${TLS_SAN_TEMPLATE_PATH:-/opt/sugarkube/systemd/etc/rancher/k3s/config.yaml.d/10-sugarkube-tls.yaml}"
TLS_SAN_DEST_NAME="10-sugarkube-tls.yaml"

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
  shift 2
  local -a extra_env=("$@")
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
    local env_entry
    for env_entry in "${extra_env[@]}"; do
      if [ -n "${env_entry}" ]; then
        printf 'Environment=%s\n' "${env_entry}"
      fi
    done
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

render_tls_san_config() {
  local template="${TLS_SAN_TEMPLATE_PATH}"
  local dest_dir="${K3S_CONFIG_DIR}/config.yaml.d"
  local dest="${dest_dir}/${TLS_SAN_DEST_NAME}"
  if [ ! -f "${template}" ]; then
    log "TLS SAN template ${template} not found; skipping"
    return 2
  fi

  mkdir -p "${dest_dir}"
  local tmp
  tmp="$(mktemp "${dest}.XXXXXX")"

  local regaddr="${SUGARKUBE_API_REGADDR:-}"
  regaddr="${regaddr//\\/\\\\}"
  regaddr="${regaddr//\"/\\\"}"

  local wrote=0
  while IFS= read -r line || [ -n "${line}" ]; do
    local rendered
    rendered="${line//\$\{SUGARKUBE_API_REGADDR:-\}/${regaddr}}"
    local compact
    compact="$(printf '%s' "${rendered}" | tr -d '[:space:]')"
    if [ "${compact}" = '-""' ]; then
      continue
    fi
    printf '%s\n' "${rendered}" >>"${tmp}"
    wrote=1
  done <"${template}"

  if [ "${wrote}" -eq 0 ]; then
    rm -f "${tmp}"
    log "Rendered TLS SAN config is empty; skipping"
    return 1
  fi

  chmod 0644 "${tmp}"

  local changed=1
  if [ -f "${dest}" ] && cmp -s "${tmp}" "${dest}"; then
    changed=0
  fi

  if [ "${changed}" -eq 1 ]; then
    log "Updating TLS SAN configuration at ${dest}"
    mv "${tmp}" "${dest}"
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

  local flannel_iface
  flannel_iface="${SUGARKUBE_FLANNEL_IFACE:-}"

  local -a changed_services=()
  local unit
  for unit in k3s.service k3s-agent.service; do
    if unit_exists "${unit}"; then
      local -a env_vars=()
      if [ "${unit}" = "k3s.service" ] && [ -n "${flannel_iface}" ]; then
        env_vars+=("K3S_FLANNEL_IFACE=${flannel_iface}")
      fi
      if write_dropin "${unit}" "${ip}" "${env_vars[@]}"; then
        changed_services+=("${unit}")
      else
        log "Drop-in for ${unit} already up-to-date"
      fi
    else
      log "Unit ${unit} not found; skipping"
    fi
  done

  local tls_rendered=0
  if render_tls_san_config; then
    tls_rendered=1
  else
    local tls_status=$?
    if [ "${tls_status}" -gt 1 ]; then
      log "Failed to render TLS SAN configuration (exit ${tls_status})"
    fi
  fi

  if [ "${tls_rendered}" -eq 1 ] && unit_exists "k3s.service"; then
    local already_present=0
    local existing
    for existing in "${changed_services[@]}"; do
      if [ "${existing}" = "k3s.service" ]; then
        already_present=1
        break
      fi
    done
    if [ "${already_present}" -eq 0 ]; then
      changed_services+=("k3s.service")
    fi
  fi

  restart_services_if_needed "${changed_services[@]}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
