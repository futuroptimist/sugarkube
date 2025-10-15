#!/usr/bin/env bash
# k3s_preflight.sh — prepare kernel modules and sysctl for k3s-ready networking.
# Usage: sudo just k3s-preflight (idempotent; prints applied toggles).

set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo --preserve-env "$0" "$@"
fi

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_ROOT_DIR="${ARTIFACT_ROOT:-${REPO_ROOT}/artifacts}"
ARTIFACT_DIR="${ARTIFACT_ROOT_DIR}/k3s-preflight"
LOG_FILE="${ARTIFACT_DIR}/preflight.log"
mkdir -p "${ARTIFACT_DIR}"
touch "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

MODULES_FILE="/etc/modules-load.d/sugarkube-k3s.conf"
SYSCTL_FILE="/etc/sysctl.d/99-sugarkube-k3s.conf"

changed=0
if [[ ! -f "${MODULES_FILE}" ]]; then
  printf '# Managed by scripts/k3s_preflight.sh\n' >"${MODULES_FILE}"
  changed=1
fi
if ! grep -q '^br_netfilter$' "${MODULES_FILE}"; then
  echo "br_netfilter" >>"${MODULES_FILE}"
  changed=1
fi

if modprobe br_netfilter 2>/dev/null; then
  echo "br_netfilter module loaded"
else
  echo "Warning: failed to load br_netfilter" >&2
fi

read -r -d '' SYSCTL_CONTENT <<'CFG'
# Managed by scripts/k3s_preflight.sh
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
CFG

if [[ ! -f "${SYSCTL_FILE}" ]] || ! cmp -s <(printf '%s' "${SYSCTL_CONTENT}") "${SYSCTL_FILE}"; then
  printf '%s\n' "${SYSCTL_CONTENT}" >"${SYSCTL_FILE}"
  changed=1
fi

declare -A SYSCTL_VALUES=(
  [net.ipv4.ip_forward]=1
  [net.bridge.bridge-nf-call-iptables]=1
  [net.bridge.bridge-nf-call-ip6tables]=1
)

for key in "${!SYSCTL_VALUES[@]}"; do
  value=${SYSCTL_VALUES[${key}]}
  current=$(sysctl -n "${key}" 2>/dev/null || echo "")
  if [[ "${current}" != "${value}" ]]; then
    changed=1
  fi
  sysctl -w "${key}=${value}" >/dev/null
  echo "Applied ${key}=${value}"
done

sysctl --system >/dev/null 2>&1 || true

if [[ ${changed} -eq 0 ]]; then
  echo "k3s preflight already satisfied"
else
  echo "k3s preflight complete"
fi
