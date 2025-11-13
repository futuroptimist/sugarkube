#!/usr/bin/env bash
# Purpose: Prepare kernel parameters and sysctls commonly required before installing k3s.
# Usage: sudo ./scripts/k3s_preflight.sh [--config-dir PATH]
set -Eeuo pipefail

# Source shared kube-proxy library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091  # Library resolves at runtime
source "${SCRIPT_DIR}/lib/kube_proxy.sh"

CONFIG_DIR="/etc/rancher/k3s/config.yaml.d"
KUBE_PROXY_CONFIG="${CONFIG_DIR}/10-kube-proxy.yaml"
KUBE_PROXY_LOG_STATE="/var/lib/sugarkube/kube-proxy-mode.log"

APT_UPDATED=0

apt_update_once() {
  if [[ ${APT_UPDATED} -eq 0 ]]; then
    if command -v apt-get >/dev/null 2>&1; then
      if apt-get -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        update >/dev/null 2>&1; then
        changes+=("apt-get update (nftables)")
      else
        changes+=("ERROR: apt-get update failed while preparing nftables installation")
        return 1
      fi
    else
      return 1
    fi
    APT_UPDATED=1
  fi
  return 0
}

ensure_nft_binary() {
  if command -v nft >/dev/null 2>&1; then
    local nft_path
    nft_path="$(command -v nft)"
    changes+=("nft binary present at ${nft_path}")
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    changes+=("ERROR: nft binary missing and apt-get unavailable to install nftables")
    return 1
  fi

  if ! apt_update_once; then
    return 1
  fi

  if DEBIAN_FRONTEND=noninteractive \
    apt-get -o Acquire::Retries=5 \
    -o Acquire::http::Timeout=30 \
    -o Acquire::https::Timeout=30 \
    install -y --no-install-recommends nftables >/dev/null 2>&1; then
    changes+=("installed nftables package to provide nft binary")
    return 0
  fi

  changes+=("ERROR: failed to install nftables package; nft binary still missing")
  return 1
}

ensure_kube_proxy_config() {
  local desired tmp_file
  desired=$'kube-proxy-arg:\n  - proxy-mode=nftables\n'

  if [[ ! -d "${CONFIG_DIR}" ]]; then
    if mkdir -p "${CONFIG_DIR}"; then
      changes+=("created ${CONFIG_DIR}")
    else
      changes+=("ERROR: failed to create ${CONFIG_DIR}")
      return 1
    fi
  fi

  tmp_file="$(mktemp)"
  printf '%s' "${desired}" >"${tmp_file}"

  if [[ ! -f "${KUBE_PROXY_CONFIG}" ]] || \
    ! cmp -s "${tmp_file}" "${KUBE_PROXY_CONFIG}"; then
    if install -m 0644 "${tmp_file}" "${KUBE_PROXY_CONFIG}"; then
      changes+=("wrote kube-proxy nftables config at ${KUBE_PROXY_CONFIG}")
    else
      changes+=("ERROR: failed to write ${KUBE_PROXY_CONFIG}")
      rm -f "${tmp_file}"
      return 1
    fi
  else
    changes+=("kube-proxy nftables config already present at ${KUBE_PROXY_CONFIG}")
  fi

  rm -f "${tmp_file}"
  return 0
}

log_kube_proxy_status_once() {
  local mode="$1"
  local nft_status="$2"
  local nft_path="$3"
  local message
  local state_dir
  state_dir="$(dirname "${KUBE_PROXY_LOG_STATE}")"

  message="kube-proxy mode=${mode} nft=${nft_status}"

  mkdir -p "${state_dir}" 2>/dev/null || true

  if [[ ! -f "${KUBE_PROXY_LOG_STATE}" ]]; then
    if command -v logger >/dev/null 2>&1; then
      local logger_msg
      if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
        logger_msg="${message} path=${nft_path}"
      else
        logger_msg="${message}"
      fi
      logger -t sugarkube-k3s-preflight "${logger_msg}" || true
    fi
  fi

  if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
    printf '%s path=%s\n' "${message}" "${nft_path}" >"${KUBE_PROXY_LOG_STATE}"
  else
    printf '%s\n' "${message}" >"${KUBE_PROXY_LOG_STATE}"
  fi
}

LAST_KUBE_PROXY_MODE="unknown"
LAST_NFT_STATUS="missing"
LAST_NFT_PATH=""

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

  LAST_KUBE_PROXY_MODE="${configured_mode:-unknown}"
  LAST_NFT_STATUS="missing"
  LAST_NFT_PATH=""

  # Check for required binaries based on configured mode
  if [[ "$configured_mode" == "nftables" ]]; then
    if command -v nft >/dev/null 2>&1; then
      changes+=("kube-proxy mode: nftables (nft binary found)")
      LAST_NFT_STATUS="present"
      LAST_NFT_PATH="$(command -v nft)"
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

  LAST_KUBE_PROXY_MODE="${configured_mode:-unknown}"
  if [[ "$LAST_NFT_STATUS" != "present" ]] && command -v nft >/dev/null 2>&1; then
    LAST_NFT_STATUS="present"
    LAST_NFT_PATH="$(command -v nft)"
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

preflight_failure=0

if ! ensure_kube_proxy_config; then
  preflight_failure=1
fi

if ! ensure_nft_binary; then
  preflight_failure=1
fi

# Check kube-proxy mode configuration
if ! check_kube_proxy_mode; then
  printf 'k3s preflight adjustments:\n'
  for entry in "${changes[@]}"; do
    printf '  - %s\n' "${entry}"
  done
  exit 1
fi

if [[ ${preflight_failure} -ne 0 ]]; then
  printf 'k3s preflight adjustments:\n'
  for entry in "${changes[@]}"; do
    printf '  - %s\n' "${entry}"
  done
  exit 1
fi

log_kube_proxy_status_once "${LAST_KUBE_PROXY_MODE}" "${LAST_NFT_STATUS}" "${LAST_NFT_PATH}"

printf 'k3s preflight adjustments:\n'
for entry in "${changes[@]}"; do
  printf '  - %s\n' "${entry}"
done
