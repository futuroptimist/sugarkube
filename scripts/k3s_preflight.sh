#!/usr/bin/env bash
# k3s_preflight.sh - Prepare kernel modules and sysctls for k3s workloads.
# Usage: sudo ./scripts/k3s_preflight.sh
# Loads br_netfilter, enables IPv4 forwarding, and ensures bridge nf sysctls are present.

set -Eeuo pipefail

apply_sysctl() {
  local key="$1" value="$2"
  if sysctl -n "${key}" 2>/dev/null | grep -qx "${value}"; then
    printf '✅ %s already %s\n' "${key}" "${value}"
    return
  fi
  sudo sysctl -w "${key}=${value}" >/dev/null
  printf '✅ Set %s=%s\n' "${key}" "${value}"
}

main() {
  if ! lsmod | grep -q '^br_netfilter'; then
    sudo modprobe br_netfilter
    printf '✅ Loaded br_netfilter\n'
  else
    printf '✅ br_netfilter already loaded\n'
  fi
  apply_sysctl net.ipv4.ip_forward 1
  apply_sysctl net.bridge.bridge-nf-call-iptables 1
  apply_sysctl net.bridge.bridge-nf-call-ip6tables 1
  apply_sysctl net.bridge.bridge-nf-call-arptables 1
}

main "$@"
