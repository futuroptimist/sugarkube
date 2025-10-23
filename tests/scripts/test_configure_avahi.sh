#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../.. && pwd)"
cd "${repo_root}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

conf_path="${tmp_dir}/avahi-daemon.conf"
log_dir="${tmp_dir}/logs"

cat >"${conf_path}" <<'CONF'
[wide-area]
enable-wide-area=yes
CONF

env \
  AVAHI_CONF_PATH="${conf_path}" \
  SUGARKUBE_LOG_DIR="${log_dir}" \
  SYSTEMCTL_BIN= \
  SUGARKUBE_MDNS_INTERFACE=eth1 \
  SUGARKUBE_MDNS_IPV4_ONLY=1 \
  bash scripts/configure_avahi.sh

grep -q '^\[server\]' "${conf_path}"
grep -q '^allow-interfaces=eth1$' "${conf_path}"
grep -q '^use-ipv4=yes$' "${conf_path}"
grep -q '^use-ipv6=no$' "${conf_path}"

if [ ! -f "${conf_path}.bak" ]; then
  echo "Backup was not created" >&2
  exit 1
fi

initial_hash="$(sha256sum "${conf_path}" | awk '{print $1}')"

env \
  AVAHI_CONF_PATH="${conf_path}" \
  SUGARKUBE_LOG_DIR="${log_dir}" \
  SYSTEMCTL_BIN= \
  SUGARKUBE_MDNS_INTERFACE=eth1 \
  SUGARKUBE_MDNS_IPV4_ONLY=1 \
  bash scripts/configure_avahi.sh

second_hash="$(sha256sum "${conf_path}" | awk '{print $1}')"

if [ "${initial_hash}" != "${second_hash}" ]; then
  echo "Configuration changed on second run" >&2
  diff -u <(printf '%s\n' "${initial_hash}") <(printf '%s\n' "${second_hash}") || true
  exit 1
fi

if [ ! -f "${log_dir}/configure_avahi.log" ]; then
  echo "Log file was not created" >&2
  exit 1
fi
