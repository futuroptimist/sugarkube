#!/usr/bin/env bash
set -euo pipefail

CONF="${AVAHI_CONF_PATH:-/etc/avahi/avahi-daemon.conf}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN-systemctl}"
LOG_DIR="${SUGARKUBE_LOG_DIR:-/var/log/sugarkube}"
LOG_FILE="${LOG_DIR}/configure_avahi.log"
RUNTIME_DIR="${SUGARKUBE_RUNTIME_DIR:-${SUGARKUBE_RUN_DIR:-/run/sugarkube}}"
WLAN_IFACE="${SUGARKUBE_WLAN_INTERFACE:-wlan0}"
WLAN_GUARD_FILE="${RUNTIME_DIR}/wlan-disabled"
PUBLISH_WORKSTATION="${SUGARKUBE_AVAHI_PUBLISH_WORKSTATION:-yes}"
ALLOW_INTERFACES_OVERRIDE="${SUGARKUBE_AVAHI_ALLOW_INTERFACES:-}"
PREFERRED_IFACE="${SUGARKUBE_MDNS_INTERFACE:-}"

log() {
  local ts
  ts="$(date --iso-8601=seconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S')"
  mkdir -p "${LOG_DIR}"
  printf '%s %s\n' "${ts}" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

log_kv() {
  local event message
  mkdir -p "${LOG_DIR}"
  event="$1"
  shift || true
  message="ts=$(date -Is) event=${event}"
  for kv in "$@"; do
    message+=" ${kv}"
  done
  printf '%s\n' "${message}" | tee -a "${LOG_FILE}" >/dev/null
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

determine_auto_allow_interface() {
  if ! command -v ip >/dev/null 2>&1; then
    return 0
  fi

  local iface_list=()
  mapfile -t iface_list < <(ip -o link show up 2>/dev/null | \
    awk -F': ' '{print $2}' | \
    awk -F'@' '{print $1}' | \
    awk '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); if ($0 != "" && $0 != "lo") print $0;}' | \
    sort -u) || true

  if [ "${#iface_list[@]}" -eq 0 ]; then
    return 0
  fi

  if [ -f "${WLAN_GUARD_FILE}" ]; then
    local filtered=()
    local candidate
    for candidate in "${iface_list[@]}"; do
      if [ "${candidate}" != "${WLAN_IFACE}" ]; then
        filtered+=("${candidate}")
      fi
    done
    iface_list=()
    if [ "${#filtered[@]}" -gt 0 ]; then
      iface_list+=("${filtered[@]}")
    fi
  fi

  if [ "${#iface_list[@]}" -eq 0 ]; then
    return 0
  fi

  if [ -n "${PREFERRED_IFACE}" ]; then
    local candidate
    for candidate in "${iface_list[@]}"; do
      if [ "${candidate}" = "${PREFERRED_IFACE}" ]; then
        printf '%s' "${PREFERRED_IFACE}"
        return 0
      fi
    done
  fi

  local candidate
  for candidate in "${iface_list[@]}"; do
    if [ "${candidate}" = "eth0" ]; then
      printf '%s' "eth0"
      return 0
    fi
  done

  if [ "${#iface_list[@]}" -eq 1 ]; then
    printf '%s' "${iface_list[0]}"
    return 0
  fi

  return 0
}

update_config() {
  local allow_mode="$1"
  local allow_value="$2"
  local tmp="$3"

  python3 <<'PY' "${CONF}" "${tmp}" "${PUBLISH_WORKSTATION}" "${allow_mode}" "${allow_value}"
import sys
from pathlib import Path

try:
    src_path = Path(sys.argv[1])
    dst_path = Path(sys.argv[2])
    publish_value = sys.argv[3]
    allow_mode = sys.argv[4]
    allow_value = sys.argv[5]

    if src_path.exists():
        try:
            original_lines = src_path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            print(f"Error reading {src_path}: {e}", file=sys.stderr)
            original_lines = []
    else:
        original_lines = []

    new_lines = []
    section = None
    publish_section_found = False
    publish_written = False
    allow_written = False

    for line in original_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            if section == "publish":
                publish_section_found = True
            new_lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else ""

        if section == "publish" and key == "publish-workstation":
            new_lines.append(f"publish-workstation={publish_value}")
            publish_written = True
            continue

        if section == "server" and key == "allow-interfaces":
            if allow_mode == "set":
                new_lines.append(f"allow-interfaces={allow_value}")
                allow_written = True
            continue

        new_lines.append(line)


    def ensure_section(lines, name):
        target = f"[{name}]"
        for idx, value in enumerate(lines):
            if value.strip().lower() == target.lower():
                start = idx + 1
                end = start
                while end < len(lines) and not lines[end].lstrip().startswith("["):
                    end += 1
                return idx, start, end
        return None, None, None


    if allow_mode == "set" and not allow_written:
        header, _, end = ensure_section(new_lines, "server")
        if header is not None:
            insert_at = end if end is not None else len(new_lines)
            new_lines.insert(insert_at, f"allow-interfaces={allow_value}")
        else:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("[server]")
            new_lines.append(f"allow-interfaces={allow_value}")

    if allow_mode == "clear":
        filtered_lines = []
        section = None
        for line in new_lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip().lower()
                filtered_lines.append(line)
                continue
            key = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else ""
            if section == "server" and key == "allow-interfaces":
                continue
            filtered_lines.append(line)
        new_lines = filtered_lines

    if publish_section_found:
        if not publish_written:
            _, _, end = ensure_section(new_lines, "publish")
            insert_at = end if end is not None else len(new_lines)
            new_lines.insert(insert_at, f"publish-workstation={publish_value}")
    else:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("[publish]")
        new_lines.append(f"publish-workstation={publish_value}")

    content = "\n".join(new_lines) + "\n"
    dst_path.write_text(content, encoding="utf-8")
    
except Exception as e:
    print(f"Error in Python script: {e}", file=sys.stderr)
    sys.exit(1)
PY
}

main() {
  log "Configuring Avahi baseline"
  ensure_config_exists
  backup_config

  local auto_allow
  auto_allow="$(determine_auto_allow_interface || true)"

  local allow_mode="clear"
  local allow_value=""
  local iface_for_log="all"
  local allow_source="none"

  if [ -n "${ALLOW_INTERFACES_OVERRIDE}" ]; then
    allow_mode="set"
    allow_value="${ALLOW_INTERFACES_OVERRIDE}"
    iface_for_log="${allow_value}"
    allow_source="override"
  elif [ -n "${auto_allow}" ]; then
    allow_mode="set"
    allow_value="${auto_allow}"
    iface_for_log="${allow_value}"
    allow_source="auto"
  elif [ -n "${PREFERRED_IFACE}" ]; then
    allow_mode="set"
    allow_value="${PREFERRED_IFACE}"
    iface_for_log="${allow_value}"
    allow_source="preferred"
  fi

  local dir tmp mode owner group
  dir="$(dirname "${CONF}")"
  tmp="$(mktemp "${dir}/avahi-daemon.conf.XXXXXX")"
  trap 'rm -f "${tmp}"' EXIT

  mode=""
  owner=""
  group=""
  if [ -e "${CONF}" ]; then
    mode="$(stat -c '%a' "${CONF}" 2>/dev/null || echo '')"
    owner="$(stat -c '%u' "${CONF}" 2>/dev/null || echo '')"
    group="$(stat -c '%g' "${CONF}" 2>/dev/null || echo '')"
  fi

  update_config "${allow_mode}" "${allow_value}" "${tmp}"

  if [ -n "${mode}" ]; then
    chmod "${mode}" "${tmp}"
  else
    chmod 0644 "${tmp}"
  fi
  if [ -n "${owner}" ] && [ -n "${group}" ]; then
    chown "${owner}:${group}" "${tmp}" || true
  fi

  local before_hash="" after_hash="" outcome="skipped"
  if [ -f "${CONF}" ]; then
    before_hash="$(sha256sum "${CONF}" | awk '{print $1}')"
  fi
  after_hash="$(sha256sum "${tmp}" | awk '{print $1}')"

  if [ "${before_hash}" = "${after_hash}" ]; then
    log "No changes required for ${CONF}"
  else
    local changes=0
    if [ -f "${CONF}" ]; then
      local diff_output
      diff_output="$(diff -U0 "${CONF}" "${tmp}" || true)"
      changes=$(printf '%s\n' "${diff_output}" | sed '1,2d' |
        awk '/^[+-]/ && $0 !~ /^(\+\+\+|---)/ {count++} END {printf "%d", count}')
    else
      changes=$(wc -l <"${tmp}" | tr -d ' ')
    fi
    log "Updating ${CONF} (${changes} line(s) changed)"
    mv "${tmp}" "${CONF}"
    trap - EXIT
    restart_avahi_if_needed
    outcome="applied"
  fi

  log_kv avahi_baseline "outcome=${outcome}" "iface=${iface_for_log}" "allow_source=${allow_source}" "publish_workstation=${PUBLISH_WORKSTATION}"
}

main "$@"
