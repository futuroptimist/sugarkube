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

# Ensure the kube-proxy configuration enforces nftables mode.
# Usage: kube_proxy::ensure_nftables_config [CONFIG_DIR] [CONFIG_FILE_NAME]
# Emits INFO/ERROR prefixed messages describing the actions taken.
kube_proxy::ensure_nftables_config() {
  local config_dir="${1:-/etc/rancher/k3s/config.yaml.d}"
  local config_file_name="${2:-10-kube-proxy.yaml}"
  local config_path="${config_dir}/${config_file_name}"
  local desired=$'kube-proxy-arg:\n  - proxy-mode=nftables\n'
  local tmp_file

  if [[ ! -d "${config_dir}" ]]; then
    if mkdir -p "${config_dir}"; then
      printf 'INFO: created config directory %s\n' "${config_dir}"
    else
      printf 'ERROR: failed to create %s\n' "${config_dir}"
      return 1
    fi
  fi

  tmp_file="$(mktemp)" || {
    printf 'ERROR: failed to create temporary file for kube-proxy config\n'
    return 1
  }

  printf '%s' "${desired}" >"${tmp_file}"

  if [[ ! -f "${config_path}" ]] || ! cmp -s "${tmp_file}" "${config_path}"; then
    if install -m 0644 "${tmp_file}" "${config_path}"; then
      printf 'INFO: wrote kube-proxy nftables config at %s\n' "${config_path}"
    else
      printf 'ERROR: failed to write kube-proxy config at %s\n' "${config_path}"
      rm -f "${tmp_file}"
      return 1
    fi
  else
    printf 'INFO: kube-proxy nftables config already present at %s\n' "${config_path}"
  fi

  rm -f "${tmp_file}"
  return 0
}
