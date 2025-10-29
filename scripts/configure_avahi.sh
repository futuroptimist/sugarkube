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
FORCE_IPV4_ONLY="${SUGARKUBE_MDNS_IPV4_ONLY:-0}"
ALLOW_INTERFACES_OVERRIDE="${SUGARKUBE_AVAHI_ALLOW_INTERFACES:-}"
PREFERRED_IFACE="${SUGARKUBE_MDNS_INTERFACE:-}"
DISABLE_WLAN_DURING_BOOTSTRAP="${SUGARKUBE_DISABLE_WLAN_DURING_BOOTSTRAP:-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_AVAHI_BIN="${SUGARKUBE_CHECK_AVAHI_BIN:-${SCRIPT_DIR}/check_avahi_config_effective.sh}"
STRICT_AVAHI="${SUGARKUBE_STRICT_AVAHI:-0}"
AVAHI_HOSTS_PATH="${SUGARKUBE_AVAHI_HOSTS_PATH:-/etc/avahi/hosts}"
EXPECTED_IPV4="${SUGARKUBE_EXPECTED_IPV4:-}"
MDNS_HOSTNAME="${SUGARKUBE_MDNS_HOSTNAME:-${HOSTNAME:-}}"
AVAHI_HOSTS_OUTCOME="skipped"
# Unless explicitly disabled, force enable-dbus=yes so Avahi exposes D-Bus.
FORCE_ENABLE_DBUS=1
if [ "${SUGARKUBE_AVAHI_DBUS_DISABLED:-0}" = "1" ]; then
  FORCE_ENABLE_DBUS=0
fi
# Default to disabling wide-area DNS-SD unless explicitly requested.
ENABLE_WIDE_AREA_RAW="${SUGARKUBE_ENABLE_WIDE_AREA:-0}"
case "$(printf '%s' "${ENABLE_WIDE_AREA_RAW}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    ENABLE_WIDE_AREA_VALUE="yes"
    ;;
  *)
    ENABLE_WIDE_AREA_VALUE="no"
    ;;
esac
# Temporary file used during atomic write; referenced by EXIT trap safely
TMP_AVAHI_TMPFILE=""

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
    log "avahi-daemon restart complete; configuration reload confirmed"
  else
    log "avahi-daemon not active; skipping restart"
  fi
}

ensure_avahi_hosts_entry() {
  AVAHI_HOSTS_OUTCOME="skipped"

  if [ -z "${MDNS_HOSTNAME}" ]; then
    log "Skipping Avahi hosts update; hostname unavailable"
    return 0
  fi

  if [ -z "${EXPECTED_IPV4}" ]; then
    log "Skipping Avahi hosts update; expected IPv4 not provided"
    return 0
  fi

  local hosts_dir tmp mode owner group
  hosts_dir="$(dirname "${AVAHI_HOSTS_PATH}")"
  if [ ! -d "${hosts_dir}" ]; then
    log "Creating Avahi hosts directory ${hosts_dir}"
    mkdir -p "${hosts_dir}"
  fi

  if [ ! -e "${AVAHI_HOSTS_PATH}" ]; then
    log "Creating Avahi hosts file at ${AVAHI_HOSTS_PATH}"
    touch "${AVAHI_HOSTS_PATH}"
  fi

  mode=""
  owner=""
  group=""
  if [ -e "${AVAHI_HOSTS_PATH}" ]; then
    mode="$(stat -c '%a' "${AVAHI_HOSTS_PATH}" 2>/dev/null || echo '')"
    owner="$(stat -c '%u' "${AVAHI_HOSTS_PATH}" 2>/dev/null || echo '')"
    group="$(stat -c '%g' "${AVAHI_HOSTS_PATH}" 2>/dev/null || echo '')"
  fi

  tmp="$(mktemp "${AVAHI_HOSTS_PATH}.XXXXXX")"
  python3 - <<'PY' \
    "${AVAHI_HOSTS_PATH}" \
    "${tmp}" \
    "${MDNS_HOSTNAME}" \
    "${EXPECTED_IPV4}"
import ipaddress
import sys
from pathlib import Path

src_path = Path(sys.argv[1])
dst_path = Path(sys.argv[2])
hostname = sys.argv[3].strip()
ipv4 = sys.argv[4].strip()

try:
    ipaddress.IPv4Address(ipv4)
except ipaddress.AddressValueError as exc:
    print(f"Invalid IPv4 {ipv4}: {exc}", file=sys.stderr)
    sys.exit(1)

try:
    existing = src_path.read_text(encoding="utf-8").splitlines()
except FileNotFoundError:
    existing = []
except Exception as exc:  # pragma: no cover - defensive
    print(f"Error reading {src_path}: {exc}", file=sys.stderr)
    sys.exit(1)

new_lines = []
for line in existing:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        new_lines.append(line)
        continue
    parts = stripped.split()
    if len(parts) < 2:
        new_lines.append(line)
        continue
    ip = parts[0]
    hosts = [part for part in parts[1:] if part != hostname]
    if len(hosts) != len(parts[1:]):
        if hosts:
            new_lines.append(f"{ip} {' '.join(hosts)}")
        continue
    new_lines.append(line)

new_lines.append(f"{ipv4} {hostname}")
content = "\n".join(new_lines).rstrip("\n") + "\n"
dst_path.write_text(content, encoding="utf-8")
PY

  if [ ! -f "${tmp}" ]; then
    log "Failed to create Avahi hosts temp file ${tmp}"
    return 1
  fi

  if [ -f "${AVAHI_HOSTS_PATH}" ] && cmp -s "${AVAHI_HOSTS_PATH}" "${tmp}"; then
    rm -f "${tmp}"
    AVAHI_HOSTS_OUTCOME="unchanged"
    return 0
  fi

  if [ -n "${mode}" ]; then
    chmod "${mode}" "${tmp}"
  else
    chmod 0644 "${tmp}"
  fi
  if [ -n "${owner}" ] && [ -n "${group}" ]; then
    chown "${owner}:${group}" "${tmp}" || true
  fi

  mv "${tmp}" "${AVAHI_HOSTS_PATH}"
  AVAHI_HOSTS_OUTCOME="updated"
  log "Ensured Avahi hosts entry for ${MDNS_HOSTNAME} (${EXPECTED_IPV4})"
  return 0
}

run_avahi_effective_check() {
  local target_conf="${1:-${CONF}}"

  if [ ! -x "${CHECK_AVAHI_BIN}" ]; then
    log "Avahi config check helper ${CHECK_AVAHI_BIN} not executable; skipping"
    return 0
  fi

  local use_ipv4="" use_ipv6="" allow_interfaces="" deny_interfaces=""
  local disable_publishing="" enable_dbus="" wide_area=""
  local -a warning_codes=()
  local -a strict_hints=()
  local -A hint_seen=()

  local check_output=""
  check_output="$(AVAHI_CONF_PATH="${target_conf}" "${CHECK_AVAHI_BIN}" 2>&1)"
  local status=$?
  if [ "${status}" -ne 0 ]; then
    log "Avahi config check failed with status ${status}: ${check_output}"
    return "${status}"
  fi

  local line
  while IFS= read -r line; do
    if [ -z "${line}" ]; then
      continue
    fi
    case "${line}" in
      use_ipv4=*)
        use_ipv4="${line#use_ipv4=}"
        ;;
      use_ipv6=*)
        use_ipv6="${line#use_ipv6=}"
        ;;
      allow_interfaces=*)
        allow_interfaces="${line#allow_interfaces=}"
        ;;
      deny_interfaces=*)
        deny_interfaces="${line#deny_interfaces=}"
        ;;
      disable_publishing=*)
        disable_publishing="${line#disable_publishing=}"
        ;;
      enable_dbus=*)
        enable_dbus="${line#enable_dbus=}"
        ;;
      wide_area=*)
        wide_area="${line#wide_area=}"
        ;;
      warning=*)
        local payload code message hint
        payload="${line#warning=}"
        if [[ "${payload}" == *"|"* ]]; then
          code="${payload%%|*}"
          message="${payload#*|}"
        else
          code="${payload}"
          message="${payload}"
        fi
        log "Avahi config warning (${code}): ${message}"
        warning_codes+=("${code}")
        hint=""
        case "${code}" in
          allow_interfaces_suffix)
            hint="Set SUGARKUBE_FIX_AVAHI=1 or remove .IPv4/.IPv6 suffixes from allow-interfaces."
            ;;
          disable_publishing)
            hint="Set disable-publishing=no or remove the directive to allow publishing."
            ;;
          dbus_disabled)
            hint="Set enable-dbus=yes so Avahi can register services."
            ;;
          protocols_disabled)
            hint="Enable at least one of use-ipv4 or use-ipv6 for mDNS traffic."
            ;;
          allow_interfaces_fix_failed)
            hint="Review file permissions and update allow-interfaces manually."
            ;;
        esac
        if [ -n "${hint}" ]; then
          if [ -z "${hint_seen["${hint}"]+x}" ]; then
            strict_hints+=("${hint}")
            hint_seen["${hint}"]=1
          fi
        fi
        ;;
      fix_applied=*)
        local fix_code
        fix_code="${line#fix_applied=}"
        log "Avahi config auto-fix applied: ${fix_code}"
        ;;
    esac
  done <<<"${check_output}"

  log_kv avahi_config_effective \
    "use_ipv4=${use_ipv4}" \
    "use_ipv6=${use_ipv6}" \
    "allow=${allow_interfaces}" \
    "deny=${deny_interfaces}" \
    "disable_publishing=${disable_publishing}" \
    "enable_dbus=${enable_dbus}" \
    "wide_area=${wide_area}"

  if [ "${STRICT_AVAHI}" = "1" ] && [ "${#warning_codes[@]}" -gt 0 ]; then
    local hint_message="See Avahi warnings above."
    if [ "${#strict_hints[@]}" -gt 0 ]; then
      hint_message="${strict_hints[0]}"
      local idx
      for idx in "${strict_hints[@]:1}"; do
        hint_message+="; ${idx}"
      done
    fi
    log "Strict Avahi validation failed; ${hint_message}"
    return 1
  fi

  return 0
}

determine_auto_allow_interface() {
  local guard_active="$1"

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

  if [ "${guard_active}" = "1" ]; then
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

  local candidate
  for candidate in "${iface_list[@]}"; do
    if [ "${candidate}" = "eth0" ]; then
      printf '%s' "eth0"
      return 0
    fi
  done

  printf '%s' "${iface_list[0]}"
  return 0
}

update_config() {
  local allow_mode="$1"
  local allow_value="$2"
  local tmp="$3"

  python3 - <<'PY' \
    "${CONF}" \
    "${tmp}" \
    "${PUBLISH_WORKSTATION}" \
    "${allow_mode}" \
    "${allow_value}" \
    "${FORCE_IPV4_ONLY}" \
    "${FORCE_ENABLE_DBUS}" \
    "${ENABLE_WIDE_AREA_VALUE}"
import sys
from pathlib import Path

try:
    src_path = Path(sys.argv[1])
    dst_path = Path(sys.argv[2])
    publish_value = sys.argv[3]
    allow_mode = sys.argv[4]
    allow_value = sys.argv[5]
    force_ipv4_only = sys.argv[6] in ("1", "true", "yes")
    force_enable_dbus = sys.argv[7] not in ("0", "false", "no")
    enable_wide_area = sys.argv[8].lower() in ("1", "true", "yes", "on")

    if src_path.exists():
        try:
            original_lines = src_path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            print(f"Error reading {src_path}: {e}", file=sys.stderr)
            print("Aborting to avoid destroying existing configuration", file=sys.stderr)
            sys.exit(1)
    else:
        original_lines = []

    new_lines = []
    section = None
    publish_section_found = False
    publish_written = False
    allow_written = False
    v4_written = False
    v6_written = False
    enable_dbus_written = False
    wide_area_written = False

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

        if section == "server" and key == "enable-dbus":
            if force_enable_dbus:
                new_lines.append("enable-dbus=yes")
                enable_dbus_written = True
                continue
            enable_dbus_written = True
            new_lines.append(line)
            continue

        if section == "wide-area" and key == "enable-wide-area":
            desired = "yes" if enable_wide_area else "no"
            new_lines.append(f"enable-wide-area={desired}")
            wide_area_written = True
            continue

        if section == "server" and key == "use-ipv4":
            if force_ipv4_only:
                new_lines.append("use-ipv4=yes")
                v4_written = True
                continue
        if section == "server" and key == "use-ipv6":
            if force_ipv4_only:
                new_lines.append("use-ipv6=no")
                v6_written = True
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

    if force_enable_dbus and not enable_dbus_written:
        header, _, end = ensure_section(new_lines, "server")
        if header is not None:
            insert_at = end if end is not None else len(new_lines)
            new_lines.insert(insert_at, "enable-dbus=yes")
        else:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("[server]")
            new_lines.append("enable-dbus=yes")

    desired_wide_area = "yes" if enable_wide_area else "no"
    if not wide_area_written:
        header, _, end = ensure_section(new_lines, "wide-area")
        if header is not None:
            insert_at = end if end is not None else len(new_lines)
            new_lines.insert(insert_at, f"enable-wide-area={desired_wide_area}")
        else:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("[wide-area]")
            new_lines.append(f"enable-wide-area={desired_wide_area}")

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

    # Enforce IPv4-only knobs when requested
    if force_ipv4_only:
        header, start, end = ensure_section(new_lines, "server")
        if header is None:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append("[server]")
            start = len(new_lines)
            end = start
        if not v4_written:
            insert_at = end if end is not None else len(new_lines)
            new_lines.insert(insert_at, "use-ipv4=yes")
            end = insert_at + 1
        if not v6_written:
            insert_at = end if end is not None else len(new_lines)
            new_lines.insert(insert_at, "use-ipv6=no")

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

  local guard_active="0"
  if [ "${DISABLE_WLAN_DURING_BOOTSTRAP}" = "1" ] && [ -f "${WLAN_GUARD_FILE}" ]; then
    guard_active="1"
  fi

  local auto_allow
  auto_allow="$(determine_auto_allow_interface "${guard_active}" || true)"

  local allow_mode="clear"
  local allow_value=""
  local iface_for_log="all"
  local allow_source="auto"

  if [ -n "${ALLOW_INTERFACES_OVERRIDE}" ]; then
    allow_mode="set"
    allow_value="${ALLOW_INTERFACES_OVERRIDE}"
    iface_for_log="${allow_value}"
    allow_source="override"
  else
    if [ -n "${PREFERRED_IFACE}" ]; then
      if [ "${guard_active}" = "1" ] && [ "${PREFERRED_IFACE}" = "${WLAN_IFACE}" ]; then
        log "Preferred interface ${PREFERRED_IFACE} blocked by guard ${WLAN_GUARD_FILE}"
      else
        allow_mode="set"
        allow_value="${PREFERRED_IFACE}"
        iface_for_log="${allow_value}"
        allow_source="preferred"
      fi
    fi

    if [ "${allow_mode}" != "set" ] && [ -n "${auto_allow}" ]; then
      allow_mode="set"
      allow_value="${auto_allow}"
      iface_for_log="${allow_value}"
      allow_source="auto"
    fi
  fi

  if [ "${allow_mode}" != "set" ]; then
    log "No allow-interfaces candidate resolved; defaulting to eth0"
    allow_mode="set"
    allow_value="eth0"
    iface_for_log="${allow_value}"
    allow_source="default"
  fi

  if [ -z "${allow_value}" ]; then
    log "allow-interfaces resolved empty; forcing eth0"
    allow_value="eth0"
    iface_for_log="${allow_value}"
    if [ -z "${allow_source}" ]; then
      allow_source="default"
    else
      allow_source="${allow_source}-fallback"
    fi
  fi

  local dir tmp mode owner group
  dir="$(dirname "${CONF}")"
  tmp="$(mktemp "${dir}/avahi-daemon.conf.XXXXXX")"
  TMP_AVAHI_TMPFILE="${tmp}"
  trap '[ -n "${TMP_AVAHI_TMPFILE:-}" ] && rm -f "${TMP_AVAHI_TMPFILE}"' EXIT

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

  if ! run_avahi_effective_check "${tmp}"; then
    log "Avahi configuration validation failed after update attempt"
    return 1
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

  ensure_avahi_hosts_entry
  if [ "${AVAHI_HOSTS_OUTCOME}" = "updated" ] && [ "${outcome}" != "applied" ]; then
    restart_avahi_if_needed
  fi

  log_kv avahi_baseline \
    "outcome=${outcome}" \
    "iface=${iface_for_log}" \
    "allow_source=${allow_source}" \
    "publish_workstation=${PUBLISH_WORKSTATION}" \
    "wide_area=${ENABLE_WIDE_AREA_VALUE}" \
    "force_enable_dbus=${FORCE_ENABLE_DBUS}"
  log_kv avahi_hosts \
    "outcome=${AVAHI_HOSTS_OUTCOME}" \
    "hostname=${MDNS_HOSTNAME}" \
    "ipv4=${EXPECTED_IPV4}"
}

main "$@"
