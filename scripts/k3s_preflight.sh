#!/usr/bin/env bash
# k3s_preflight.sh - Prepare kernel modules and sysctl toggles commonly required for k3s workloads.
# Usage: sudo scripts/k3s_preflight.sh
set -euo pipefail

sudo_prefix=()
if [[ $(id -u) -ne 0 ]]; then
  sudo_prefix=(sudo)
fi

declare -a changes

ensure_module() {
  local module="$1"
  if lsmod | awk '{print $1}' | grep -qx "${module}"; then
    echo "[k3s-preflight] Kernel module ${module} already loaded"
    return
  fi
  if "${sudo_prefix[@]}" modprobe "${module}"; then
    echo "[k3s-preflight] Loaded ${module}"
    changes+=("module:${module}")
  else
    echo "[k3s-preflight] Failed to load module ${module}" >&2
  fi
}

apply_sysctl() {
  local key="$1" value="$2"
  local current
  current=$(sysctl -n "${key}" 2>/dev/null || echo "missing")
  if [[ "${current}" == "${value}" ]]; then
    echo "[k3s-preflight] sysctl ${key} already ${value}"
    return
  fi
  if "${sudo_prefix[@]}" sysctl -w "${key}=${value}" >/dev/null; then
    echo "[k3s-preflight] Set ${key}=${value}"
    changes+=("sysctl:${key}=${value}")
  else
    echo "[k3s-preflight] Failed to set ${key}" >&2
  fi
}

ensure_module br_netfilter
apply_sysctl net.ipv4.ip_forward 1
apply_sysctl net.bridge.bridge-nf-call-iptables 1
apply_sysctl net.bridge.bridge-nf-call-ip6tables 1

if [[ ${#changes[@]} -eq 0 ]]; then
  echo "[k3s-preflight] No changes required; system already k3s-ready."
else
  printf '[k3s-preflight] Applied %d change(s): %s\n' "${#changes[@]}" "${changes[*]}"
fi
