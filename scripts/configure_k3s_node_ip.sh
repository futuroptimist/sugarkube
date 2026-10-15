#!/usr/bin/env bash
# Sugarkube managed Ethernet preparation and pre-start refresh
set -euo pipefail
umask 022

IFACE="${SUGARKUBE_MDNS_INTERFACE:-eth0}"
IP_CMD="${IP_CMD:-ip}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN-systemctl}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_k3s_node_ip.log"
SYSTEMD_SYSTEM_DIR="${SYSTEMD_SYSTEM_DIR:-/etc/systemd/system}"
UNIT_SEARCH_PATHS="${SYSTEMD_UNIT_PATHS:-/etc/systemd/system:/lib/systemd/system:/usr/lib/systemd/system}"
DROPIN_NAME="10-node-ip.conf"
K3S_CONFIG_DIR="${K3S_CONFIG_DIR:-/etc/rancher/k3s}"
K3S_DATA_DIR="${K3S_DATA_DIR:-/var/lib/rancher/k3s}"
TLS_SAN_TEMPLATE_PATH="${TLS_SAN_TEMPLATE_PATH:-/opt/sugarkube/systemd/etc/rancher/k3s/config.yaml.d/10-sugarkube-tls.yaml}"
TLS_SAN_DEST_NAME="10-sugarkube-tls.yaml"

log() {
  local ts
  ts="$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  prestart_file_action prepare "${LOG_FILE}" || return 2
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

select_primary_ipv4_from_ip_output() {
  awk '
    $3 == "inet" && /scope global/ && !/secondary|tentative|deprecated/ {
      split($4, addr, "/")
      if (addr[1] != "") {
        candidate = addr[1]
        count++
      }
    }
    END { if (count == 1) print candidate }
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
    if "${SYSTEMCTL_BIN}" list-unit-files --no-legend "${unit}" 2>/dev/null | \
      awk -v unit="${unit}" '$1 == unit { found=1 } END { exit !found }'; then
      return 0
    fi
  fi
  return 1
}

# Write supported K3s YAML, never environment variables without a CLI binding.
write_network_config() {
  local ip="$1" iface="$2"
  local dir="${K3S_CONFIG_DIR}/config.yaml.d" dest tmp
  dest="${dir}/20-sugarkube-network.yaml"
  prestart_file_action prepare "${dest}" || return 2
  if [ -L "${dest}" ]; then
    log "Refusing symlink ${dest}"
    return 2
  fi
  tmp="$(mktemp "${dir}/.network.XXXXXX")" || return 2
  printf '# Managed by configure_k3s_node_ip.sh\nnode-ip: "%s"\nflannel-iface: "%s"\n' \
    "${ip}" "${iface}" >"${tmp}" || { rm -f "${tmp}"; return 2; }
  chmod 0644 "${tmp}" || { rm -f "${tmp}"; return 2; }
  if [ -f "${dest}" ] && cmp -s "${tmp}" "${dest}"; then
    rm -f "${tmp}"
    return 1
  fi
  if [ -e "${dest}" ] && ! head -n 1 "${dest}" | \
    grep -qx '# Managed by configure_k3s_node_ip.sh'; then
    rm -f "${tmp}"
    log "Refusing to overwrite unmanaged ${dest}"
    return 2
  fi
  if { unit_exists k3s.service || [ -e "${K3S_DATA_DIR}/server/db" ]; } && \
    [ "${PREPARE_SERVER}" != 1 ]; then
    rm -f "${tmp}"
    log "Server configuration change requires --prepare-server after quorum review; no restart"
    printf '%s\n' 'Server change blocked: review quorum, then use --prepare-server (stages only).' >&2
    return 2
  fi
  prestart_file_action publish "${dest}" "${tmp}" || { rm -f "${tmp}"; return 2; }
  log "Prepared ${dest}; no service restart performed"
}

# Prepare trusted directories and durably publish each prerequisite before hooks.
prestart_file_action() {
  python3 - "$@" <<'PYINSTALL'
import os
import stat
import sys
from pathlib import Path

action, target = sys.argv[1:3]
target = Path(target)
uid = os.geteuid()

def inspect(path, directory=False):
    info = path.lstat()
    if path.is_symlink() or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise SystemExit("Untrusted pre-start installation path")
    # Non-root runs may use a sticky temporary ancestor for isolated tests/user
    # files; root installations must have exclusively root-trusted ancestry.
    temporary = directory and uid != 0 and bool(info.st_mode & stat.S_ISVTX)
    if not temporary and ((uid == 0 and info.st_uid != 0) or info.st_mode & 0o022):
        raise SystemExit("Untrusted pre-start installation ownership or permissions")
    if not directory and info.st_uid != uid:
        raise SystemExit("Pre-start file must belong to its installing user")

def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def prepare_directory(path):
    if path.exists() or path.is_symlink():
        for ancestor in (path, *path.parents):
            inspect(ancestor, directory=True)
    else:
        prepare_directory(path.parent)
        path.mkdir(mode=0o755)
        path.chmod(0o755)
        inspect(path, directory=True)
    # Include existing ancestors left by an interrupted previous attempt.
    for ancestor in (path, *path.parents):
        sync_directory(ancestor)

prepare_directory(target.parent)
if target.exists() or target.is_symlink():
    inspect(target)
    with target.open("rb") as existing:
        os.fsync(existing.fileno())
if action == "publish":
    temporary = Path(sys.argv[3])
    if temporary.parent != target.parent:
        raise SystemExit("Pre-start temporary file must share its destination directory")
    inspect(temporary)
    with temporary.open("rb") as staged:
        os.fsync(staged.fileno())
    os.replace(temporary, target)
    sync_directory(target.parent)
elif action != "prepare":
    raise SystemExit("Unsupported pre-start file operation")
PYINSTALL
}

# Install before persisting an address: every subsequent systemd start refreshes it.
# Nothing here reloads systemd or starts K3s; the installer/reboot loads the drop-ins.
install_start_refresh() {
  local source="${BASH_SOURCE[0]}" runtime="${K3S_CONFIG_DIR}/sugarkube-network-prestart.sh"
  local ip_binary unit dest tmp marker
  ip_binary="$(command -v "${IP_CMD}")" || return 2
  # Keep systemd arguments literal: no specifiers, escaping, whitespace or shell expansion.
  for value in "${K3S_CONFIG_DIR}" "${LOG_DIR}" "${ip_binary}"; do
    [[ "${value}" =~ ^/[a-zA-Z0-9_./:-]+$ ]] || {
      log "Unsupported path for required network pre-start hook"; return 2;
    }
  done
  for unit in runtime k3s.service k3s-agent.service; do
    if [ "${unit}" = runtime ]; then
      dest="${runtime}"
      marker='# Sugarkube managed Ethernet preparation and pre-start refresh'
    else
      dest="${SYSTEMD_SYSTEM_DIR}/${unit}.d/20-sugarkube-network.conf"
      marker='# Managed by configure_k3s_node_ip.sh'
    fi
    prestart_file_action prepare "${dest}" || return 2
    [ ! -L "${dest}" ] || { log "Refusing symlink ${dest}"; return 2; }
    tmp="$(mktemp "${dest}.XXXXXX")" || return 2
    if [ "${unit}" = runtime ]; then
      cat "${source}" >"${tmp}" || { rm -f "${tmp}"; return 2; }
    else
      printf '%s\n' "${marker}" '[Unit]' 'Wants=network-online.target' \
        'After=network-online.target' '[Service]' \
        "ExecStartPre=/usr/bin/timeout 30s /bin/bash ${runtime} --refresh-on-start ${IFACE} ${K3S_CONFIG_DIR} ${LOG_DIR} ${ip_binary}" \
        >"${tmp}" || { rm -f "${tmp}"; return 2; }
    fi
    chmod 0644 "${tmp}" || { rm -f "${tmp}"; return 2; }
    if [ -f "${dest}" ] && cmp -s "${tmp}" "${dest}"; then
      rm -f "${tmp}"
      continue
    fi
    if [ -e "${dest}" ] && ! head -n 2 "${dest}" | grep -qx "${marker}"; then
      rm -f "${tmp}"; log "Refusing unmanaged pre-start file ${dest}"; return 2
    fi
    if { unit_exists k3s.service || [ -e "${K3S_DATA_DIR}/server/db" ]; } && \
      [ "${PREPARE_SERVER}" != 1 ]; then
      rm -f "${tmp}"
      log "Installing/updating server pre-start refresh requires --prepare-server"
      return 2
    fi
    prestart_file_action publish "${dest}" "${tmp}" || { rm -f "${tmp}"; return 2; }
  done
}

# Only retire the exact legacy format this helper owned. Preserve custom files.
retire_legacy_dropins() {
  local unit file
  for unit in k3s.service k3s-agent.service; do
    file="${SYSTEMD_SYSTEM_DIR}/${unit}.d/${DROPIN_NAME}"
    [ -e "${file}" ] || continue
    if [ ! -f "${file}" ] || [ -L "${file}" ] || ! awk '
      NR == 1 { if ($0 != "[Service]") exit 1; next }
      /^Environment=K3S_NODE_IP=[0-9.]+$/ { ip++; next }
      /^Environment=K3S_FLANNEL_IFACE=[a-zA-Z0-9_.:-]+$/ { iface++; next }
      { exit 1 }
      END { if (ip != 1 || iface > 1) exit 1 }
    ' "${file}"; then
      log "Custom legacy drop-in retained: ${file}; review overrides manually"
      continue
    fi
    # Preserve the old content without leaving a .conf file loaded by systemd.
    if [ -e "${file}.pre-yaml" ] || [ -L "${file}.pre-yaml" ]; then
      log "Backup already exists: ${file}.pre-yaml; legacy drop-in retained"
      continue
    fi
    # Matching YAML does not authorize a pending legacy-file migration on retry.
    if { unit_exists k3s.service || [ -e "${K3S_DATA_DIR}/server/db" ]; } && \
      [ "${PREPARE_SERVER:-0}" != 1 ]; then
      log "Legacy server configuration change requires --prepare-server; file preserved"
      printf '%s\n' 'Legacy migration blocked: review quorum, then use --prepare-server.' >&2
      return 2
    fi
    mv "${file}" "${file}.pre-yaml"
    log "Preserved legacy drop-in at ${file}.pre-yaml; daemon-reload required"
  done
}

render_tls_san_config() {
  local template="${TLS_SAN_TEMPLATE_PATH}"
  local dest_dir="${K3S_CONFIG_DIR}/config.yaml.d"
  local dest="${dest_dir}/${TLS_SAN_DEST_NAME}"
  if [ ! -f "${template}" ]; then
    log "TLS SAN template ${template} not found; skipping"
    return 2
  fi

  prestart_file_action prepare "${dest}" || return 3
  local tmp
  tmp="$(mktemp "${dest}.XXXXXX")" || return 3

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
    printf '%s\n' "${rendered}" >>"${tmp}" || { rm -f "${tmp}"; return 3; }
    wrote=1
  done <"${template}"

  if [ "${wrote}" -eq 0 ]; then
    rm -f "${tmp}"
    log "Rendered TLS SAN config is empty; skipping"
    return 1
  fi

  chmod 0644 "${tmp}" || { rm -f "${tmp}"; return 3; }

  local changed=1
  if [ -f "${dest}" ] && cmp -s "${tmp}" "${dest}"; then
    changed=0
  fi

  if [ "${changed}" -eq 1 ]; then
    log "Updating TLS SAN configuration at ${dest}"
    prestart_file_action publish "${dest}" "${tmp}" || { rm -f "${tmp}"; return 3; }
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
  output="$("${IP_CMD}" -4 -o addr show "${IFACE}" scope global 2>/dev/null)" || return 1
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

main() {
  PREPARE_SERVER=0
  local refresh_only=0
  case "${1:-}" in
    --prepare-server) PREPARE_SERVER=1; shift ;;
    --refresh-on-start)
      # Invoked by the installed unit on every start, including ordinary reboots.
      [ "$#" -eq 5 ] || return 2
      IFACE="$2"; K3S_CONFIG_DIR="$3"; LOG_DIR="$4"; IP_CMD="$5"
      LOG_FILE="${LOG_DIR}/configure_k3s_node_ip.log"
      SUGARKUBE_FLANNEL_IFACE="${IFACE}"
      PREPARE_SERVER=1; refresh_only=1; shift 5
      local managed="${K3S_CONFIG_DIR}/config.yaml.d/20-sugarkube-network.yaml"
      # The explicitly installed hook owns this reserved YAML path. It must be
      # able to bootstrap an absent file after interrupted first preparation,
      # without persisting a literal address before refresh protection exists.
      if [ -L "${managed}" ] || { [ -e "${managed}" ] && \
        { [ ! -f "${managed}" ] || ! head -n 1 "${managed}" | \
          grep -qx '# Managed by configure_k3s_node_ip.sh'; }; }; then
        printf '%s\n' 'Unmanaged network configuration; refusing K3s start.' >&2
        return 2
      fi
      ;;
    "") ;;
    *) printf 'Usage: %s [--prepare-server]\n' "$0" >&2; return 2 ;;
  esac
  [ "$#" -eq 0 ] || return 2
  # Serialize local invocations; this is not a cluster-wide recovery lock.
  prestart_file_action prepare "${K3S_CONFIG_DIR}/.sugarkube-network.lock" || return 2
  exec 9>"${K3S_CONFIG_DIR}/.sugarkube-network.lock"
  flock -n 9 || { log "Another network configuration run is active"; return 2; }
  local ip iface status
  iface="${SUGARKUBE_FLANNEL_IFACE:-${IFACE}}"
  if [[ ! "${IFACE}" =~ ^[a-zA-Z0-9_.:-]+$ ]] || [[ "${IFACE}" == wl* ]] || \
    [ "${iface}" != "${IFACE}" ]; then
    log "Ethernet address and flannel interface must match"
    return 2
  fi
  ip="$(detect_primary_ipv4)" || return 1
  # Reject unusable/injected values before writing YAML.
  python3 - "${ip}" <<'PYIP' || return 2
import ipaddress
import sys
ip = ipaddress.IPv4Address(sys.argv[1])
if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
    raise SystemExit("Unusable Ethernet IPv4 address")
PYIP
  if [ "${refresh_only}" = 0 ]; then
    install_start_refresh || return 2
  fi
  if write_network_config "${ip}" "${iface}"; then
    :
  else
    status=$?
    [ "${status}" -eq 1 ] || return "${status}"
  fi
  if [ "${refresh_only}" = 1 ]; then
    log "Ethernet address refreshed before K3s start; no membership or Node status mutation"
    return 0
  fi
  # Preserve initial TLS template setup, but never overwrite existing SAN policy.
  local tls_dest="${K3S_CONFIG_DIR}/config.yaml.d/${TLS_SAN_DEST_NAME}"
  if [ ! -e "${tls_dest}" ] && [ ! -L "${tls_dest}" ] && \
    [ -f "${TLS_SAN_TEMPLATE_PATH}" ] && ! unit_exists k3s.service && \
    [ ! -e "${K3S_DATA_DIR}/server/db" ]; then
    if render_tls_san_config; then
      :
    else
      status=$?
      [ "${status}" -eq 1 ] || return "${status}"
    fi
  fi
  retire_legacy_dropins
  log "Configuration prepared only; verify CLI/env overrides, membership and Node status before restart"
  printf '%s\n' 'Configuration prepared; no reload or restart. Review effective CLI/env overrides and quorum.'
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
