#!/usr/bin/env bash
# shellcheck shell=bash

# Shared kube-proxy dataplane mode detection library.
# Provides functions to detect configured kube-proxy mode from k3s config files.

# Guard against multiple sourcing.
if [ -n "${SUGARKUBE_KUBE_PROXY_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_KUBE_PROXY_LIB_SOURCED=1

# Normalize requested kube-proxy mode values.
# Usage: kube_proxy::normalize_mode VALUE
# Returns: nftables, iptables, auto, or unknown
kube_proxy::normalize_mode() {
  local value="${1:-}"
  value="${value,,}"
  case "${value}" in
    nft|nftables)
      echo "nftables"
      ;;
    iptables)
      echo "iptables"
      ;;
    auto)
      echo "auto"
      ;;
    "")
      echo "unknown"
      ;;
    *)
      echo "unknown"
      ;;
  esac
}

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

# Ensure the kube-proxy configuration enforces the requested mode.
# Usage: kube_proxy::ensure_mode_config [CONFIG_DIR] MODE [CONFIG_FILE_NAME]
# Supported modes: nftables, iptables.
# Emits INFO/ERROR prefixed messages describing the actions taken.
kube_proxy::ensure_mode_config() {
  local config_dir="${1:-/etc/rancher/k3s/config.yaml.d}"
  local mode="${2:-nftables}"
  local config_file_name="${3:-10-kube-proxy.yaml}"
  local config_path="${config_dir}/${config_file_name}"
  local desired=""
  local tmp_file

  case "${mode}" in
    nft|nftables)
      desired=$'kube-proxy-arg:\n  - proxy-mode=nftables\n'
      mode="nftables"
      ;;
    iptables)
      desired=$'kube-proxy-arg:\n  - proxy-mode=iptables\n'
      ;;
    *)
      printf 'ERROR: unsupported kube-proxy mode "%s"\n' "${mode}"
      return 1
      ;;
  esac

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
      printf 'INFO: wrote kube-proxy %s config at %s\n' "${mode}" "${config_path}"
    else
      printf 'ERROR: failed to write kube-proxy config at %s\n' "${config_path}"
      rm -f "${tmp_file}"
      return 1
    fi
  else
    printf 'INFO: kube-proxy %s config already present at %s\n' "${mode}" "${config_path}"
  fi

  rm -f "${tmp_file}"
  return 0
}

# Backwards compatibility wrapper that enforces nftables mode.
kube_proxy::ensure_nftables_config() {
  kube_proxy::ensure_mode_config "$1" "nftables" "$2"
}

# Configure the update-alternatives entry for a binary.
kube_proxy::set_update_alternative() {
  local name="$1"
  local path="$2"

  if ! command -v update-alternatives >/dev/null 2>&1; then
    printf 'ERROR: update-alternatives unavailable while configuring %s\n' "${name}"
    return 1
  fi

  if ! update-alternatives --query "${name}" >/dev/null 2>&1; then
    printf 'INFO: update-alternatives entry %s not managed; skipped (%s)\n' "${name}" "${path}"
    return 0
  fi

  if update-alternatives --set "${name}" "${path}" >/dev/null 2>&1; then
    printf 'INFO: update-alternatives %s -> %s\n' "${name}" "${path}"
    return 0
  fi

  printf 'ERROR: failed to set update-alternatives %s -> %s\n' "${name}" "${path}"
  return 1
}

# Ensure the iptables family binaries use their legacy implementations.
kube_proxy::configure_iptables_legacy_alternatives() {
  local alt
  local legacy_path
  local failures=0
  local names=(
    iptables
    ip6tables
    iptables-save
    iptables-restore
    ip6tables-save
    ip6tables-restore
  )

  for alt in "${names[@]}"; do
    legacy_path="/usr/sbin/${alt}-legacy"
    if [[ ! -x "${legacy_path}" ]]; then
      printf 'WARN: legacy binary %s missing; skipping %s\n' "${legacy_path}" "${alt}"
      continue
    fi
    if ! kube_proxy::set_update_alternative "${alt}" "${legacy_path}"; then
      failures=$((failures + 1))
    fi
  done

  if [[ ${failures} -gt 0 ]]; then
    return 1
  fi
  return 0
}

# Read the current iptables variant, version, and executable path.
kube_proxy::read_iptables_details() {
  local variant="missing"
  local version="unavailable"
  local path=""
  local version_line

  if command -v iptables >/dev/null 2>&1; then
    path="$(command -v iptables)"
    variant="unknown"
    version="unknown"
    version_line="$(iptables -V 2>/dev/null | head -n1 || echo "")"
    if [[ -n "${version_line}" ]]; then
      version="$(printf '%s' "${version_line}" | awk '{print $2}')"
      if printf '%s' "${version_line}" | grep -qi 'legacy'; then
        variant="legacy"
      elif printf '%s' "${version_line}" | grep -qi 'nf_tables'; then
        variant="nf_tables"
      fi
    fi
  fi

  printf '%s;%s;%s\n' "${variant}" "${version}" "${path}"
}

# Ensure that legacy iptables binaries are available and selected via update-alternatives.
# Usage: kube_proxy::ensure_iptables_legacy [INSTALL_CALLBACK]
# The optional INSTALL_CALLBACK is executed when iptables binaries are missing.
kube_proxy::ensure_iptables_legacy() {
  local installer="${1:-}"
  local variant version path

  if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
    if [[ -n "${installer}" ]]; then
      if ! "${installer}"; then
        printf 'ERROR: failed to install iptables legacy backend\n'
        return 1
      fi
    else
      printf 'ERROR: iptables binaries missing and no installer provided\n'
      return 1
    fi
  fi

  if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
    printf 'ERROR: iptables or ip6tables missing after installation attempt\n'
    return 1
  fi

  IFS=';' read -r variant version path < <(kube_proxy::read_iptables_details)

  if [[ "${variant}" != "legacy" ]]; then
    if ! kube_proxy::configure_iptables_legacy_alternatives; then
      printf 'ERROR: failed to switch iptables alternatives to legacy\n'
      return 1
    fi
    IFS=';' read -r variant version path < <(kube_proxy::read_iptables_details)
  fi

  if [[ "${variant}" != "legacy" ]]; then
    printf 'ERROR: expected iptables legacy backend but detected %s\n' "${variant}"
    return 1
  fi

  if [[ -n "${path}" ]]; then
    printf 'INFO: iptables binary %s variant=%s version=%s\n' "${path}" "${variant}" "${version}"
  else
    printf 'INFO: iptables binary variant=%s version=%s\n' "${variant}" "${version}"
  fi

  printf 'DETAILS:%s;%s;%s\n' "${variant}" "${version}" "${path}"
  return 0
}
