#!/usr/bin/env bash
# shellcheck disable=SC1091  # optional helper libraries resolve at runtime
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/fs.sh
. "${SCRIPT_DIR}/lib/fs.sh"

fs::ensure_umask 022

cluster="${SUGARKUBE_CLUSTER:?SUGARKUBE_CLUSTER is required}"
environment="${SUGARKUBE_ENV:?SUGARKUBE_ENV is required}"
: "${HOSTNAME:?HOSTNAME is required}"
SRV_HOST="${HOSTNAME%.local}.local"
export SRV_HOST
role="${ROLE:?ROLE is required}"
case "${role}" in
  bootstrap|server)
    ;;
  *)
    echo "Unsupported ROLE: ${role}" >&2
    exit 2
    ;;
esac
export PORT="${PORT:-6443}"
export PHASE="${PHASE:-}"
leader_value="${LEADER:-}"
if [ -z "${leader_value}" ]; then
  leader_value="${SRV_HOST}"
else
  while [[ "${leader_value}" == *"." ]]; do
    leader_value="${leader_value%.}"
  done
  leader_value="${leader_value%.local}"
  if [ -n "${leader_value}" ]; then
    leader_value="${leader_value}.local"
  else
    leader_value="${SRV_HOST}"
  fi
fi
export LEADER="${leader_value}"
service_dir="${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}"
if [ -n "${SUGARKUBE_AVAHI_SERVICE_FILE:-}" ]; then
  service_file="${SUGARKUBE_AVAHI_SERVICE_FILE}"
else
  service_file="${service_dir}/k3s-${cluster}-${environment}.service"
fi
service_dir="$(dirname "${service_file}")"
SERVICE_TYPE="_k3s-${cluster}-${environment}._tcp"

install -d -m 755 "${service_dir}"

service_tmp_file=""
cleanup_service_tmp() {
  if [ -n "${service_tmp_file}" ] && [ -e "${service_tmp_file}" ]; then
    rm -f "${service_tmp_file}"
  fi
}
trap cleanup_service_tmp EXIT

TXT_IP4=""
TXT_IP6=""
TXT_HOST="${HOSTNAME}"

if command -v python3 >/dev/null 2>&1; then
  txt_ip_payload="$(python3 - <<'PY'
import ipaddress
import json
import os
import subprocess


def run_command(command):
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


iface_hint = os.environ.get("SUGARKUBE_MDNS_INTERFACE", "").strip()
hostname_tokens = []

hostname_output = run_command(["hostname", "-I"])
if hostname_output:
    hostname_tokens = [token for token in hostname_output.split() if token]

IGNORE_IFACE_NAMES = {"lo"}
IGNORE_IFACE_PREFIXES = (
    "docker",
    "veth",
    "virbr",
    "cni",
    "flannel",
    "kube-",
    "zt",
    "tailscale",
    "podman",
    "br-",
    "lxdbr",
)
IGNORE_IFACE_KINDS = {"bridge"}
IGNORE_IFACE_FLAGS = {"LOOPBACK"}


def gather_iface_metadata():
    data = run_command(["ip", "-j", "link", "show"])
    if not data:
        return {}
    try:
        payload = json.loads(data)
    except Exception:
        return {}
    metadata = {}
    for entry in payload:
        iface_name = entry.get("ifname") or entry.get("name") or ""
        if not iface_name:
            continue
        kind = ""
        if isinstance(entry.get("linkinfo"), dict):
            kind = entry["linkinfo"].get("info_kind") or ""
        if not kind:
            kind = entry.get("link_type") or ""
        flags = entry.get("flags") or []
        metadata[iface_name] = {
            "kind": kind.lower() if isinstance(kind, str) else "",
            "flags": {flag.upper() for flag in flags if isinstance(flag, str)},
        }
    return metadata


IFACE_METADATA = gather_iface_metadata()


def interface_blacklisted(name):
    if not name:
        return True
    if name in IGNORE_IFACE_NAMES:
        return True
    for prefix in IGNORE_IFACE_PREFIXES:
        if name.startswith(prefix):
            return True
    meta = IFACE_METADATA.get(name, {})
    kind = meta.get("kind", "")
    if kind in IGNORE_IFACE_KINDS:
        return True
    flags = meta.get("flags") or set()
    if flags.intersection(IGNORE_IFACE_FLAGS):
        return True
    return False


def interface_allowed(name, default_iface):
    if not name:
        return False
    if name == iface_hint:
        return True
    if default_iface and name == default_iface and not interface_blacklisted(name):
        return True
    return not interface_blacklisted(name)


def gather_addr_entries(family):
    flag = "-4" if family == 4 else "-6"
    try:
        data = subprocess.check_output(
            ["ip", flag, "-j", "addr", "show"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    try:
        payload = json.loads(data)
    except Exception:
        return []
    entries = []
    for entry in payload:
        iface_name = entry.get("ifname", "")
        for addr_info in entry.get("addr_info", []):
            family_name = addr_info.get("family")
            if family == 4 and family_name != "inet":
                continue
            if family == 6 and family_name != "inet6":
                continue
            local_ip = addr_info.get("local")
            if not local_ip:
                continue
            try:
                ip_obj = ipaddress.ip_address(local_ip)
            except ValueError:
                continue
            if family == 4 and not isinstance(ip_obj, ipaddress.IPv4Address):
                continue
            if family == 6 and not isinstance(ip_obj, ipaddress.IPv6Address):
                continue
            if ip_obj.is_unspecified or ip_obj.is_multicast:
                continue
            if isinstance(ip_obj, ipaddress.IPv4Address):
                if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                    continue
            if isinstance(ip_obj, ipaddress.IPv6Address):
                if ip_obj.is_loopback:
                    continue
            entries.append((iface_name, str(ip_obj)))
    return entries


def pick_from_interface(entries, target_iface, allow_blacklisted=False):
    if not target_iface:
        return ""
    for iface_name, candidate in entries:
        if iface_name != target_iface:
            continue
        if allow_blacklisted or not interface_blacklisted(iface_name):
            return candidate
    return ""


def default_interface(family):
    flag = "-4" if family == 4 else "-6"
    output = run_command(["ip", flag, "route", "show", "default"])
    if not output:
        return ""
    for line in output.splitlines():
        parts = line.split()
        if "dev" in parts:
            try:
                return parts[parts.index("dev") + 1]
            except (IndexError, ValueError):
                continue
    return ""


def choose_ip(family):
    entries = gather_addr_entries(family)
    default_iface_name = default_interface(family)

    if iface_hint:
        candidate = pick_from_interface(entries, iface_hint, allow_blacklisted=True)
        if candidate:
            return candidate

    if default_iface_name:
        candidate = pick_from_interface(entries, default_iface_name)
        if candidate:
            return candidate

    allowed_candidates = []
    disallowed = set()
    for iface_name, candidate in entries:
        if interface_allowed(iface_name, default_iface_name):
            allowed_candidates.append(candidate)
        else:
            disallowed.add(candidate)

    if allowed_candidates:
        return allowed_candidates[0]

    if entries:
        # Entries existed, but filtering rejected them all; return empty string to indicate
        # that discovery succeeded yet no allowed addresses were found.
        return ""

    for token in hostname_tokens:
        try:
            ip_obj = ipaddress.ip_address(token)
        except ValueError:
            continue
        if family == 4 and isinstance(ip_obj, ipaddress.IPv4Address):
            if ip_obj.is_unspecified or ip_obj.is_multicast or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                continue
            return str(ip_obj)
        if family == 6 and isinstance(ip_obj, ipaddress.IPv6Address):
            if ip_obj.is_unspecified or ip_obj.is_multicast or ip_obj.is_loopback:
                continue
            return str(ip_obj)
    return ""


ip4 = choose_ip(4)
ip6 = choose_ip(6)

if ip4:
    print(f"ip4={ip4}")
if ip6:
    print(f"ip6={ip6}")
PY
)"
else
  txt_ip_payload=""
fi
if [ -n "${txt_ip_payload}" ]; then
  while IFS='=' read -r key value; do
    case "${key}" in
      ip4) TXT_IP4="${value}" ;;
      ip6) TXT_IP6="${value}" ;;
    esac
  done <<<"${txt_ip_payload}"
fi

export TXT_IP4 TXT_IP6 TXT_HOST

ensure_mdns_target_resolvable() {
  if ! command -v avahi-resolve-host-name >/dev/null 2>&1; then
    echo "avahi-resolve-host-name not found; skipping SRV target preflight" >&2
    return 0
  fi

  local resolve_cmd=("avahi-resolve-host-name" "${SRV_HOST}" -4 "--timeout=1")
  local hosts_path="${SUGARKUBE_AVAHI_HOSTS_PATH:-/etc/avahi/hosts}"
  local expected_ipv4="${SUGARKUBE_EXPECTED_IPV4:-}"
  local nss_ok=0
  local resolve_ok=0
  local browse_ok=0
  local outcome="fail"
  local hosts_updated=0
  local avahi_hostname_ran=0

  gather_resolution_status() {
    nss_ok=0
    resolve_ok=0

    if command -v getent >/dev/null 2>&1; then
      local getent_ipv4=""
      getent_ipv4="$(getent hosts "${SRV_HOST}" 2>/dev/null | awk 'NR==1 {print $1}' | head -n1)"
      if [ -n "${getent_ipv4}" ]; then
        if [ -n "${expected_ipv4}" ] && [ "${getent_ipv4}" != "${expected_ipv4}" ]; then
          nss_ok=0
        else
          nss_ok=1
        fi
      fi
    fi

    if "${resolve_cmd[@]}" >/dev/null 2>&1; then
      resolve_ok=1
    fi

    if [ "${nss_ok}" = "1" ] || [ "${resolve_ok}" = "1" ]; then
      return 0
    fi
    return 1
  }

  ensure_expected_ipv4() {
    if [ -n "${expected_ipv4}" ]; then
      return 0
    fi

    local iface addr_candidates
    iface="${SUGARKUBE_MDNS_INTERFACE:-}"
    addr_candidates="$(hostname -I 2>/dev/null || true)"
    expected_ipv4="$(python3 - "${iface}" "${addr_candidates}" 2>/dev/null <<'PY' || true
import ipaddress
import json
import subprocess
import sys

iface_hint = sys.argv[1].strip()
hostname_tokens = [token for token in sys.argv[2].split() if token]

IGNORE_IFACE_NAMES = {"lo"}
IGNORE_IFACE_PREFIXES = (
    "docker",
    "veth",
    "virbr",
    "cni",
    "flannel",
    "kube-",
    "zt",
    "tailscale",
    "podman",
    "br-",
    "lxdbr",
)
IGNORE_IFACE_KINDS = {
    "bridge",
}
IGNORE_IFACE_FLAGS = {"LOOPBACK"}


def valid_ipv4(candidate):
    try:
        ip = ipaddress.IPv4Address(candidate)
    except ipaddress.AddressValueError:
        return False
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return False
    return True


def gather_iface_metadata():
    try:
        data = subprocess.check_output(
            ["ip", "-j", "link", "show"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return {}

    try:
        payload = json.loads(data)
    except Exception:
        return {}

    metadata = {}
    for entry in payload:
        iface_name = entry.get("ifname") or entry.get("name") or ""
        if not iface_name:
            continue
        link_type = ""
        if isinstance(entry.get("linkinfo"), dict):
            link_type = entry["linkinfo"].get("info_kind") or ""
        if not link_type:
            link_type = entry.get("link_type") or ""
        flags = entry.get("flags") or []
        metadata[iface_name] = {
            "kind": link_type.lower() if isinstance(link_type, str) else "",
            "flags": {flag.upper() for flag in flags if isinstance(flag, str)},
        }
    return metadata


IFACE_METADATA = gather_iface_metadata()


def interface_blacklisted(name):
    if not name:
        return True
    if name in IGNORE_IFACE_NAMES:
        return True
    for prefix in IGNORE_IFACE_PREFIXES:
        if name.startswith(prefix):
            return True
    meta = IFACE_METADATA.get(name, {})
    kind = meta.get("kind", "")
    if kind in IGNORE_IFACE_KINDS:
        return True
    flags = meta.get("flags") or set()
    if flags.intersection(IGNORE_IFACE_FLAGS):
        return True
    return False


def interface_allowed(name, default_iface):
    if not name:
        return False
    if name == iface_hint:
        return True
    if default_iface and name == default_iface and not interface_blacklisted(name):
        return True
    return not interface_blacklisted(name)


def gather_ip_entries():
    try:
        data = subprocess.check_output(
            ["ip", "-j", "-4", "addr", "show"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []

    try:
        payload = json.loads(data)
    except Exception:
        return []

    entries = []
    for entry in payload:
        iface_name = entry.get("ifname", "")
        for addr_info in entry.get("addr_info", []):
            if addr_info.get("family") != "inet":
                continue
            if addr_info.get("scope") not in {"global", "site"}:
                continue
            local_ip = addr_info.get("local")
            if not local_ip:
                continue
            entries.append((iface_name, local_ip))
    return entries


def pick_from_interface(entries, target_iface, allow_blacklisted=False):
    if not target_iface:
        return None
    for iface_name, candidate_ip in entries:
        if iface_name != target_iface:
            continue
        if not valid_ipv4(candidate_ip):
            continue
        if allow_blacklisted or not interface_blacklisted(iface_name):
            return candidate_ip
    return None


def default_interface():
    try:
        output = subprocess.check_output(
            ["ip", "-4", "route", "show", "default"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None
    for line in output.splitlines():
        parts = line.split()
        if "dev" in parts:
            try:
                return parts[parts.index("dev") + 1]
            except (IndexError, ValueError):
                continue
    return None


def choose_ip():
    entries = gather_ip_entries()
    default_iface_name = default_interface()

    candidate = pick_from_interface(entries, iface_hint, allow_blacklisted=True)
    if candidate:
        return candidate

    if default_iface_name:
        candidate = pick_from_interface(entries, default_iface_name)
        if candidate:
            return candidate

    had_entries = bool(entries)
    allowed_candidates = []
    disallowed_ips = set()
    for iface_name, candidate_ip in entries:
        if not valid_ipv4(candidate_ip):
            continue
        if interface_allowed(iface_name, default_iface_name):
            allowed_candidates.append(candidate_ip)
        else:
            disallowed_ips.add(candidate_ip)

    if allowed_candidates:
        return allowed_candidates[0]

    if had_entries:
        return None

    for candidate_ip in hostname_tokens:
        if candidate_ip in disallowed_ips:
            continue
        if valid_ipv4(candidate_ip):
            return candidate_ip

    return None


selected = choose_ip()
if selected:
    print(selected)
PY
    )"
    if [ -z "${expected_ipv4}" ]; then
      echo "Unable to determine IPv4 for ${SRV_HOST}; cannot pre-publish mDNS host" >&2
      return 1
    fi
    return 0
  }

  update_hosts_file() {
    if ! ensure_expected_ipv4; then
      return 1
    fi

    local hosts_dir owner group tmp hosts_changed=0
    hosts_dir="$(dirname "${hosts_path}")"
    install -d -m 755 "${hosts_dir}"

    if [ -e "${hosts_path}" ]; then
      owner="$(stat -c '%u' "${hosts_path}" 2>/dev/null || echo '')"
      group="$(stat -c '%g' "${hosts_path}" 2>/dev/null || echo '')"
    else
      owner=""
      group=""
      : >"${hosts_path}"
      hosts_changed=1
    fi

    tmp="$(mktemp "${hosts_path}.XXXXXX")" || return 1
    if ! python3 - <<'PY' \
      "${hosts_path}" \
      "${tmp}" \
      "${SRV_HOST}" \
      "${expected_ipv4}"
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
    then
      rm -f "${tmp}"
      return 1
    fi

    if [ ! -f "${tmp}" ]; then
      echo "Failed to build Avahi hosts temp file" >&2
      return 1
    fi

    if [ -f "${hosts_path}" ] && cmp -s "${hosts_path}" "${tmp}"; then
      rm -f "${tmp}"
      chmod 0644 "${hosts_path}" 2>/dev/null || true
    else
      hosts_changed=1
      chmod 0644 "${tmp}"
      if [ -n "${owner}" ] && [ -n "${group}" ]; then
        chown "${owner}:${group}" "${tmp}" || true
      fi
      mv "${tmp}" "${hosts_path}"
    fi

    if [ "${hosts_changed}" = "1" ] && [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" != "1" ] && command -v systemctl >/dev/null 2>&1; then
      systemctl reload avahi-daemon || systemctl restart avahi-daemon || true
    fi

    return 0
  }

  run_avahi_set_host_name() {
    if [ "${avahi_hostname_ran}" = "1" ]; then
      return 0
    fi
    if ! command -v avahi-set-host-name >/dev/null 2>&1; then
      return 0
    fi

    local raw_host
    raw_host="$(hostname 2>/dev/null || true)"
    raw_host="${raw_host%%.*}"
    if [ -z "${raw_host}" ]; then
      raw_host="${SRV_HOST%.local}"
    fi
    raw_host="${raw_host%.local}"
    local avahi_host="${raw_host}.local"
    if [ -z "${avahi_host}" ]; then
      avahi_host="${SRV_HOST}"
    fi
    avahi-set-host-name "${avahi_host}" >/dev/null 2>&1 || true
    avahi_hostname_ran=1
  }

  check_browse_status() {
    browse_ok=0
    if ! command -v avahi-browse >/dev/null 2>&1; then
      return 1
    fi

    local browse_output=""
    if ! browse_output="$(avahi-browse -rt "${SERVICE_TYPE}" 2>/dev/null)"; then
      return 1
    fi
    if [ -z "${browse_output}" ]; then
      return 1
    fi
    if printf '%s\n' "${browse_output}" | grep -Fq "${SRV_HOST}"; then
      browse_ok=1
      return 0
    fi
    browse_ok=1
    return 0
  }

  emit_resolution_status() {
    local status_action="$1"
    [ -n "${status_action}" ] || status_action="fail"
    printf 'mdns resolution status action=%s nss_ok=%s resolve_ok=%s browse_ok=%s hosts_updated=%s\n' \
      "${status_action}" "${nss_ok}" "${resolve_ok}" "${browse_ok}" "${hosts_updated}" >&2
  }

  if gather_resolution_status; then
    outcome="ok"
  else
    if update_hosts_file; then
      hosts_updated=1
    fi
    if gather_resolution_status; then
      outcome="ok"
    fi
  fi

  if [ "${outcome}" != "ok" ]; then
    run_avahi_set_host_name
    if gather_resolution_status; then
      outcome="ok"
    fi
  fi

  check_browse_status || true

  if [ "${outcome}" != "ok" ] && [ "${browse_ok}" = "1" ]; then
    outcome="warn"
  fi

  emit_resolution_status "${outcome}"

  if [ "${outcome}" = "fail" ]; then
    return 1
  fi

  return 0
}


wait_for_avahi_publication() {
  local service_display timeout_seconds start_epoch pattern deadline now journal_output
  service_display="$1"
  timeout_seconds="$2"
  start_epoch="$3"

  case "${timeout_seconds}" in
    ''|*[!0-9]*)
      timeout_seconds=20
      ;;
  esac

  if ! command -v journalctl >/dev/null 2>&1; then
    echo "journalctl not available; skipping Avahi publication confirmation" >&2
    return 0
  fi

  pattern="Service \"${service_display}\" successfully established."
  deadline=$(( $(date +%s) + timeout_seconds ))

  while true; do
    now=$(date +%s)
    if [ "${now}" -gt "${deadline}" ]; then
      echo "Timed out waiting for Avahi to publish ${service_display}" >&2
      return 1
    fi

    if journal_output="$(journalctl -u avahi-daemon --since "@${start_epoch}" --no-pager 2>/dev/null)"; then
      if grep -Fq "${pattern}" <<<"${journal_output}"; then
        return 0
      fi
    else
      echo "journalctl query failed; skipping Avahi publication confirmation" >&2
      return 0
    fi

    sleep 1
  done
}

reload_avahi_daemon() {
  local service_display timeout_seconds start_epoch
  service_display="$1"
  timeout_seconds="$2"

  case "${timeout_seconds}" in
    ''|*[!0-9]*)
      timeout_seconds=20
      ;;
  esac

  if [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" = "1" ] || ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi

  start_epoch=$(($(date +%s) - 1))

  if ! systemctl reload avahi-daemon; then
    if ! systemctl restart avahi-daemon; then
      echo "Failed to reload or restart avahi-daemon" >&2
      return 1
    fi
  fi

  wait_for_avahi_publication "${service_display}" "${timeout_seconds}" "${start_epoch}"
}

if ! ensure_mdns_target_resolvable; then
  echo "Unable to ensure ${HOSTNAME} is resolvable via mDNS" >&2
  exit 1
fi

service_tmp_file="$(mktemp "${service_dir}/.k3s-mdns.XXXXXX")"
python3 - "${service_tmp_file}" <<'PY'
import html
import os
import sys

tmp_path = sys.argv[1]
cluster = os.environ["SUGARKUBE_CLUSTER"]
environment = os.environ["SUGARKUBE_ENV"]
srv_host = os.environ["SRV_HOST"]
role = os.environ["ROLE"]
port = os.environ.get("PORT", "6443")
phase = os.environ.get("PHASE", "")
leader = os.environ.get("LEADER", "")
txt_ip4 = os.environ.get("TXT_IP4", "")
txt_ip6 = os.environ.get("TXT_IP6", "")
txt_host = os.environ.get("TXT_HOST", "")

service_name = f"k3s-{cluster}-{environment}@{srv_host} ({role})"
service_type = f"_k3s-{cluster}-{environment}._tcp"

def esc(value: str) -> str:
    return html.escape(value, quote=True)

records = [
    ("k3s", "1"),
    ("cluster", cluster),
    ("env", environment),
    ("role", role),
    ("phase", phase),
    ("leader", leader),
]

if txt_host:
    records.append(("host", txt_host))
if txt_ip4:
    records.append(("ip4", txt_ip4))
if txt_ip6:
    records.append(("ip6", txt_ip6))

with open(tmp_path, "w", encoding="utf-8") as fh:
    fh.write("<?xml version=\"1.0\" standalone='no'?>\n")
    fh.write("<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">\n")
    fh.write("<service-group>\n")
    fh.write(f"  <name replace-wildcards=\"yes\">{esc(service_name)}</name>\n")
    fh.write("  <service>\n")
    fh.write(f"    <type>{esc(service_type)}</type>\n")
    fh.write(f"    <host-name>{esc(srv_host)}</host-name>\n")
    fh.write(f"    <port>{esc(str(port))}</port>\n")
    for key, value in records:
        fh.write(f"    <txt-record>{esc(f'{key}={value}')}</txt-record>\n")
    fh.write("  </service>\n")
    fh.write("</service-group>\n")
PY

if [ ! -f "${service_tmp_file}" ]; then
  echo "Failed to render Avahi service definition" >&2
  exit 1
fi

fs::atomic_install "${service_tmp_file}" "${service_file}" 0644 root root
service_tmp_file=""

service_display="k3s-${cluster}-${environment}@${SRV_HOST} (${role})"
reload_avahi_daemon "${service_display}" "${SUGARKUBE_AVAHI_WAIT_TIMEOUT:-20}"
