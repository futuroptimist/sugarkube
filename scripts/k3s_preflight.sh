#!/usr/bin/env bash
# Purpose: Prepare kernel parameters and sysctls commonly required before installing k3s.
# Usage: sudo ./scripts/k3s_preflight.sh
set -Eeuo pipefail

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

ensure_module br_netfilter
set_sysctl net.ipv4.ip_forward 1
for bridge_key in net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables; do
  if sysctl -a 2>/dev/null | grep -q "${bridge_key}"; then
    set_sysctl "${bridge_key}" 1
  else
    changes+=("sysctl ${bridge_key} unavailable; skipping")
  fi
done

printf 'k3s preflight adjustments:\n'
for entry in "${changes[@]}"; do
  printf '  - %s\n' "${entry}"
done
