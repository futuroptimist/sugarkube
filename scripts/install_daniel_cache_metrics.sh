#!/usr/bin/env bash
set -Eeuo pipefail

env_name="${1:-}"
root="${SUGARKUBE_DANIEL_CACHE_ROOT:-}"
case "${env_name}" in
  staging) endpoint=https://staging.danielsmith.io/runtime/github-metrics.json ;;
  prod) endpoint=https://danielsmith.io/runtime/github-metrics.json ;;
  *) printf 'ERROR: usage: %s staging|prod\n' "$0" >&2; exit 2 ;;
esac
if [[ -z "${root}" && ${EUID} -ne 0 ]]; then
  printf 'ERROR: installation must run as root.\n' >&2
  exit 1
fi
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install -Dm755 "${repo_root}/scripts/daniel_cache_metrics.py" \
  "${root}/usr/local/libexec/sugarkube-daniel-cache-metrics"
install -Dm644 "${repo_root}/scripts/systemd/daniel-cache-metrics.service" \
  "${root}/etc/systemd/system/daniel-cache-metrics.service"
install -Dm644 "${repo_root}/scripts/systemd/daniel-cache-metrics.timer" \
  "${root}/etc/systemd/system/daniel-cache-metrics.timer"
install -d -m0755 "${root}/etc/sugarkube" \
  "${root}/var/lib/node_exporter/textfile_collector"
printf 'DANIEL_CACHE_ENVIRONMENT=%s\nDANIEL_CACHE_URL=%s\n' "${env_name}" "${endpoint}" \
  >"${root}/etc/sugarkube/daniel-cache-metrics.env"
chmod 0644 "${root}/etc/sugarkube/daniel-cache-metrics.env"
if [[ -z "${root}" ]]; then
  systemctl daemon-reload
  systemctl enable --now daniel-cache-metrics.timer
fi
