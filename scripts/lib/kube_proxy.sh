#!/usr/bin/env bash
# shellcheck shell=bash

# Shared kube-proxy dataplane mode detection library.
# Provides functions to detect configured kube-proxy mode from k3s config files.

# Guard against multiple sourcing.
if [ -n "${SUGARKUBE_KUBE_PROXY_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_KUBE_PROXY_LIB_SOURCED=1

# Detect the configured kube-proxy mode from k3s config files.
# Usage: kube_proxy::detect_mode CONFIG_DIR
# Returns: "nftables", "iptables", or "unknown"
kube_proxy::detect_mode() {
  local config_dir="${1:-/etc/rancher/k3s/config.yaml.d}"
  local mode="unknown"
  
  if [[ -d "$config_dir" ]]; then
    for config_file in "$config_dir"/*.yaml; do
      if [[ -f "$config_file" ]]; then
        if grep -q "proxy-mode=nftables\|proxy-mode=nft" "$config_file" 2>/dev/null; then
          mode="nftables"
          break
        elif grep -q "proxy-mode=iptables" "$config_file" 2>/dev/null; then
          mode="iptables"
          break
        fi
      fi
    done
  fi
  
  echo "$mode"
}
