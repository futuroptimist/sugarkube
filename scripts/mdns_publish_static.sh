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
