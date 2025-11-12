#!/usr/bin/env bash
# Purpose: Prepare kernel parameters and sysctls commonly required before installing k3s.
# Usage: sudo ./scripts/k3s_preflight.sh [--config-dir PATH]
set -Eeuo pipefail

# Source shared kube-proxy library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/kube_proxy.sh
source "${SCRIPT_DIR}/lib/kube_proxy.sh"

CONFIG_DIR="/etc/rancher/k3s/config.yaml.d"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir)
      if [[ $# -lt 2 ]]; then
        echo "--config-dir requires a path argument" >&2
        exit 1
      fi
      CONFIG_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--config-dir PATH]" >&2
      exit 1
      ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo to adjust kernel settings." >&2
  exit 1
fi

changes=()

ensure_module() {
  local module="$1"
  if lsmod | awk '{print $1}' | grep -qx "${module}"; then
    changes+=("module ${module} already loaded")
    return
  fi
  if modprobe "${module}" 2>/dev/null; then
    changes+=("loaded module ${module}")
  else
    changes+=("failed to load module ${module}")
  fi
}

set_sysctl() {
  local key="$1" value="$2"
  local current
  current=$(sysctl -n "${key}" 2>/dev/null || echo "unset")
  if [[ "${current}" == "${value}" ]]; then
    changes+=("sysctl ${key}=${value} (unchanged)")
    return
  fi
  if sysctl -w "${key}=${value}" >/dev/null 2>&1; then
    changes+=("set sysctl ${key}=${value}")
  else
    changes+=("failed to set sysctl ${key}")
  fi
}

check_kube_proxy_mode() {
  # Determine configured proxy mode using shared library
  local configured_mode
  configured_mode=$(kube_proxy::detect_mode "$CONFIG_DIR")

  # Check for required binaries based on configured mode
  if [[ "$configured_mode" == "nftables" ]]; then
    if command -v nft >/dev/null 2>&1; then
      changes+=("kube-proxy mode: nftables (nft binary found)")
    else
      changes+=("ERROR: kube-proxy mode configured as nftables but nft binary not found")
      return 1
    fi
  elif [[ "$configured_mode" == "iptables" ]]; then
    if command -v iptables >/dev/null 2>&1; then
      local version_line
      version_line=$(iptables -V 2>/dev/null | head -n1 || echo "")
      if printf '%s' "$version_line" | grep -qi 'legacy'; then
        changes+=("kube-proxy mode: iptables (legacy binary found)")
      else
        changes+=("WARNING: kube-proxy mode configured as iptables but binary appears to be nf_tables")
      fi
    else
      changes+=("ERROR: kube-proxy mode configured as iptables but iptables binary not found")
      return 1
    fi
  else
    changes+=("kube-proxy mode: not configured or unknown")
  fi
  return 0
}

ensure_module br_netfilter
set_sysctl net.ipv4.ip_forward 1
for bridge_key in net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables; do
  if sysctl -a 2>/dev/null | grep -q "${bridge_key}"; then
    set_sysctl "${bridge_key}" 1
  else
    changes+=("sysctl ${bridge_key} unavailable; skipping")
  fi
done

# Check kube-proxy mode configuration
if ! check_kube_proxy_mode; then
  printf 'k3s preflight adjustments:\n'
  for entry in "${changes[@]}"; do
    printf '  - %s\n' "${entry}"
  done
  exit 1
fi

printf 'k3s preflight adjustments:\n'
for entry in "${changes[@]}"; do
  printf '  - %s\n' "${entry}"
done
