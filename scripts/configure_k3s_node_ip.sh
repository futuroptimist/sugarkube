#!/usr/bin/env bash
set -euo pipefail

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_k3s_node_ip.log"
if [ -z "${SYSTEMCTL_BIN+x}" ]; then
  SYSTEMCTL_BIN="systemctl"
fi

log() {
  local timestamp
  timestamp="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf '%s %s\n' "${timestamp}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

select_primary_ipv4_from_input() {
  awk '
    {
      for (i = 1; i <= NF; i++) {
        if ($i == "inet" && (i + 1) <= NF) {
          split($(i + 1), parts, "/")
          if (parts[1] != "") {
            print parts[1]
            exit
          }
        }
      }
    }
  '
}

detect_primary_ipv4() {
  local iface="$1"
  local output
  if ! command -v ip >/dev/null 2>&1; then
    log "ip command not available; cannot detect IPv4 address"
    return 1
  fi
  output="$(ip -4 -o addr show "${iface}" 2>/dev/null || true)"
  if [ -z "${output}" ]; then
    return 1
  fi
  printf '%s\n' "${output}" | select_primary_ipv4_from_input
}

service_exists() {
  local svc="$1"
  local dropin_dir="/etc/systemd/system/${svc}.d"
  local dropin_file="${dropin_dir}/10-node-ip.conf"
  if [ -d "${dropin_dir}" ] || [ -f "${dropin_file}" ]; then
    return 0
  fi
  if [ -f "/etc/systemd/system/${svc}" ] || [ -f "/lib/systemd/system/${svc}" ]; then
    return 0
  fi
  if [ -n "${SYSTEMCTL_BIN}" ] && command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    local listing
    if listing="$(${SYSTEMCTL_BIN} list-unit-files "${svc}" 2>/dev/null)"; then
      if printf '%s\n' "${listing}" | awk -v svc="${svc}" 'NR>1 && $1 == svc { found = 1 } END { exit(found ? 0 : 1) }'; then
        return 0
      fi
    fi
  fi
  return 1
}

write_dropin() {
  local svc="$1"
  local dir="/etc/systemd/system/${svc}.d"
  local target="${dir}/10-node-ip.conf"
  local tmp tmp_dest mode owner group

  mkdir -p "${dir}"
  tmp="$(mktemp)"
  printf '[Service]\nEnvironment=K3S_NODE_IP=%s\n' "${NODE_IP}" >"${tmp}"

  if [ -f "${target}" ] && cmp -s "${tmp}" "${target}"; then
    log "${target} already sets K3S_NODE_IP=${NODE_IP}"
    rm -f "${tmp}"
    return
  fi

  mode=644
  owner=0
  group=0
  if [ -e "${target}" ]; then
    mode="$(stat -c '%a' "${target}")"
    owner="$(stat -c '%u' "${target}")"
    group="$(stat -c '%g' "${target}")"
  fi

  tmp_dest="${target}.tmp.$$"
  install -m "${mode}" "${tmp}" "${tmp_dest}"
  chown "${owner}:${group}" "${tmp_dest}"
  mv "${tmp_dest}" "${target}"
  rm -f "${tmp}"

  UPDATED_SERVICES+=("${svc}")
  log "Updated ${target} with node IP ${NODE_IP}"
}

if [ "${1:-}" = "--parse-stdin" ]; then
  shift || true
  if NODE_IP="$(select_primary_ipv4_from_input)"; then
    if [ -n "${NODE_IP}" ]; then
      printf '%s\n' "${NODE_IP}"
      exit 0
    fi
  fi
  exit 1
fi

mkdir -p "${LOG_DIR}"
log "Configuring k3s node IP for interface ${IFACE}"

NODE_IP="$(detect_primary_ipv4 "${IFACE}" || true)"
if [ -z "${NODE_IP}" ]; then
  log "No IPv4 address detected on ${IFACE}; skipping drop-in creation"
  exit 1
fi
log "Detected IPv4 ${NODE_IP} on ${IFACE}"

CANDIDATES=("k3s.service" "k3s-agent.service")
SERVICES=()
for svc in "${CANDIDATES[@]}"; do
  if service_exists "${svc}"; then
    SERVICES+=("${svc}")
  else
    log "${svc} not present; skipping"
  fi
done

if [ "${#SERVICES[@]}" -eq 0 ]; then
  log "No k3s unit files found; nothing to configure"
  exit 0
fi

declare -a UPDATED_SERVICES=()
for svc in "${SERVICES[@]}"; do
  write_dropin "${svc}"
done

if [ "${#UPDATED_SERVICES[@]}" -eq 0 ]; then
  log "Existing node IP drop-ins already match ${NODE_IP}"
  exit 0
fi

if [ -z "${SYSTEMCTL_BIN}" ] || ! command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
  log "${SYSTEMCTL_BIN:-systemctl} not available; skipping daemon-reload and restarts"
  exit 0
fi

if "${SYSTEMCTL_BIN}" daemon-reload >/dev/null 2>&1; then
  log "Reloaded systemd unit definitions"
else
  log "systemctl daemon-reload failed"
fi

for svc in "${UPDATED_SERVICES[@]}"; do
  if "${SYSTEMCTL_BIN}" is-active --quiet "${svc}"; then
    if "${SYSTEMCTL_BIN}" restart "${svc}"; then
      log "Restarted ${svc}"
    else
      log "Failed to restart ${svc}"
    fi
  else
    log "${svc} inactive; restart skipped"
  fi
done
