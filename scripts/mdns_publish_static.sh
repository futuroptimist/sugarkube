#!/usr/bin/env bash
set -euo pipefail

cluster="${SUGARKUBE_CLUSTER:?SUGARKUBE_CLUSTER is required}"
environment="${SUGARKUBE_ENV:?SUGARKUBE_ENV is required}"
: "${HOSTNAME:?HOSTNAME is required}"
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
export LEADER="${LEADER:-}"
service_dir="${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}"
if [ -n "${SUGARKUBE_AVAHI_SERVICE_FILE:-}" ]; then
  service_file="${SUGARKUBE_AVAHI_SERVICE_FILE}"
else
  service_file="${service_dir}/k3s-${cluster}-${environment}.service"
fi
service_dir="$(dirname "${service_file}")"

install -d -m 755 "${service_dir}"

ensure_mdns_target_resolvable() {
  if ! command -v avahi-resolve-host-name >/dev/null 2>&1; then
    echo "avahi-resolve-host-name not found; skipping SRV target preflight" >&2
    return 0
  fi

  if avahi-resolve-host-name "${HOSTNAME}" >/dev/null 2>&1; then
    return 0
  fi

  local hosts_path="${SUGARKUBE_AVAHI_HOSTS_PATH:-/etc/avahi/hosts}"
  local expected_ipv4="${SUGARKUBE_EXPECTED_IPV4:-}"

  if [ -z "${expected_ipv4}" ]; then
    local iface addr_candidates
    iface="${SUGARKUBE_MDNS_INTERFACE:-}"
    addr_candidates="$(hostname -I 2>/dev/null || true)"
    expected_ipv4="$(
      python3 - "${iface}" "${addr_candidates}" 2>/dev/null <<'PY' || true
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
)


def valid_ipv4(candidate):
    try:
        ip = ipaddress.IPv4Address(candidate)
    except ipaddress.AddressValueError:
        return False
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return False
    return True


def interface_allowed(name, default_iface):
    if not name:
        return False
    if name == iface_hint:
        return True
    if default_iface and name == default_iface:
        return True
    if name in IGNORE_IFACE_NAMES:
        return False
    for prefix in IGNORE_IFACE_PREFIXES:
        if name.startswith(prefix):
            return False
    return True


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


def pick_from_interface(entries, target_iface):
    if not target_iface:
        return None
    for iface_name, candidate_ip in entries:
        if iface_name == target_iface and valid_ipv4(candidate_ip):
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

    candidate = pick_from_interface(entries, iface_hint)
    if candidate:
        return candidate

    if default_iface_name:
        candidate = pick_from_interface(entries, default_iface_name)
        if candidate:
            return candidate

    disallowed_ips = set()
    for iface_name, candidate_ip in entries:
        if interface_allowed(iface_name, default_iface_name):
            if valid_ipv4(candidate_ip):
                return candidate_ip
        elif valid_ipv4(candidate_ip):
            disallowed_ips.add(candidate_ip)

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
  fi

  if [ -z "${expected_ipv4}" ]; then
    echo "Unable to determine IPv4 for ${HOSTNAME}; cannot pre-publish mDNS host" >&2
    return 1
  fi

  local hosts_dir mode owner group tmp hosts_changed=0
  hosts_dir="$(dirname "${hosts_path}")"
  install -d -m 755 "${hosts_dir}"

  if [ -e "${hosts_path}" ]; then
    mode="$(stat -c '%a' "${hosts_path}" 2>/dev/null || echo '')"
    owner="$(stat -c '%u' "${hosts_path}" 2>/dev/null || echo '')"
    group="$(stat -c '%g' "${hosts_path}" 2>/dev/null || echo '')"
  else
    mode=""
    owner=""
    group=""
    touch "${hosts_path}"
    hosts_changed=1
  fi

  tmp="$(mktemp "${hosts_path}.XXXXXX")"
  python3 - <<'PY' \
    "${hosts_path}" \
    "${tmp}" \
    "${HOSTNAME}" \
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

  if [ ! -f "${tmp}" ]; then
    echo "Failed to build Avahi hosts temp file" >&2
    return 1
  fi

  if [ -f "${hosts_path}" ] && cmp -s "${hosts_path}" "${tmp}"; then
    rm -f "${tmp}"
  else
    hosts_changed=1
    if [ -n "${mode}" ]; then
      chmod "${mode}" "${tmp}"
    else
      chmod 0644 "${tmp}"
    fi
    if [ -n "${owner}" ] && [ -n "${group}" ]; then
      chown "${owner}:${group}" "${tmp}" || true
    fi
    mv "${tmp}" "${hosts_path}"
  fi

  if [ "${hosts_changed}" = "1" ] && [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" != "1" ] && \
     command -v systemctl >/dev/null 2>&1; then
    systemctl reload avahi-daemon || systemctl restart avahi-daemon || true
  fi

  if ! avahi-resolve-host-name "${HOSTNAME}" >/dev/null 2>&1; then
    echo "mDNS resolution for ${HOSTNAME} still failing after hosts update" >&2
    return 1
  fi

  return 0
}

if ! ensure_mdns_target_resolvable; then
  echo "Unable to ensure ${HOSTNAME} is resolvable via mDNS" >&2
  exit 1
fi

tmp_file="$(mktemp "${service_dir}/.k3s-mdns.XXXXXX")"
python3 - "$tmp_file" <<'PY'
import html
import os
import sys

tmp_path = sys.argv[1]
cluster = os.environ["SUGARKUBE_CLUSTER"]
environment = os.environ["SUGARKUBE_ENV"]
hostname = os.environ["HOSTNAME"]
role = os.environ["ROLE"]
port = os.environ.get("PORT", "6443")
phase = os.environ.get("PHASE", "")
leader = os.environ.get("LEADER", "")

service_name = f"k3s-{cluster}-{environment}@{hostname} ({role})"
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

with open(tmp_path, "w", encoding="utf-8") as fh:
    fh.write("<?xml version=\"1.0\" standalone='no'?>\n")
    fh.write("<!DOCTYPE service-group SYSTEM \"avahi-service.dtd\">\n")
    fh.write("<service-group>\n")
    fh.write(f"  <name replace-wildcards=\"yes\">{esc(service_name)}</name>\n")
    fh.write("  <service>\n")
    fh.write(f"    <type>{esc(service_type)}</type>\n")
    fh.write(f"    <port>{esc(str(port))}</port>\n")
    for key, value in records:
        fh.write(f"    <txt-record>{esc(f'{key}={value}')}</txt-record>\n")
    fh.write("  </service>\n")
    fh.write("</service-group>\n")
PY

install -m 644 "${tmp_file}" "${service_file}"
rm -f "${tmp_file}"

if [ "${SUGARKUBE_SKIP_SYSTEMCTL:-0}" != "1" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl reload avahi-daemon || systemctl restart avahi-daemon || true
fi
