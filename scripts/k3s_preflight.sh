#!/usr/bin/env bash
# Purpose: Prepare kernel parameters and sysctls commonly required before installing k3s.
# Usage: sudo ./scripts/k3s_preflight.sh [--config-dir PATH] [--kube-proxy-mode MODE]
set -Eeuo pipefail

# Source shared kube-proxy library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091  # Library resolves at runtime
source "${SCRIPT_DIR}/lib/kube_proxy.sh"

CONFIG_DIR="/etc/rancher/k3s/config.yaml.d"
KUBE_PROXY_LOG_STATE="/var/lib/sugarkube/kube-proxy-mode.log"

DESIRED_KUBE_PROXY_MODE="auto"
SELECTED_KUBE_PROXY_MODE="unknown"
KUBE_PROXY_MODE_SOURCE="default"

APT_UPDATED=0

apt_update_once() {
  local context="${1:-packages}"
  if [[ ${APT_UPDATED} -eq 0 ]]; then
    if command -v apt-get >/dev/null 2>&1; then
      if apt-get -o Acquire::Retries=5 \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        update >/dev/null 2>&1; then
        changes+=("apt-get update (${context})")
      else
        changes+=("ERROR: apt-get update failed while preparing ${context}")
        return 1
      fi
    else
      return 1
    fi
    APT_UPDATED=1
  fi
  return 0
}

normalize_kube_proxy_mode() {
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

select_kube_proxy_mode() {
  local desired="${DESIRED_KUBE_PROXY_MODE}"
  local env_mode
  local configured_mode

  if [[ "${desired}" != "auto" && "${desired}" != "unknown" ]]; then
    SELECTED_KUBE_PROXY_MODE="${desired}"
    KUBE_PROXY_MODE_SOURCE="cli"
  else
    env_mode="$(normalize_kube_proxy_mode "${K3S_KUBE_PROXY_MODE:-}")"
    if [[ "${env_mode}" == "nftables" || "${env_mode}" == "iptables" ]]; then
      SELECTED_KUBE_PROXY_MODE="${env_mode}"
      KUBE_PROXY_MODE_SOURCE="env"
    else
      configured_mode="$(kube_proxy::detect_mode "${CONFIG_DIR}")"
      if [[ "${configured_mode}" == "nftables" || "${configured_mode}" == "iptables" ]]; then
        SELECTED_KUBE_PROXY_MODE="${configured_mode}"
        KUBE_PROXY_MODE_SOURCE="config"
      else
        SELECTED_KUBE_PROXY_MODE="nftables"
        KUBE_PROXY_MODE_SOURCE="default"
      fi
    fi
  fi

  changes+=("kube-proxy backend selection: ${SELECTED_KUBE_PROXY_MODE} (source=${KUBE_PROXY_MODE_SOURCE})")
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

  if ! apt_update_once "nftables"; then
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

set_update_alternative() {
  local name="$1"
  local path="$2"

  if ! command -v update-alternatives >/dev/null 2>&1; then
    changes+=("ERROR: update-alternatives unavailable while configuring ${name}")
    return 1
  fi

  if ! update-alternatives --query "${name}" >/dev/null 2>&1; then
    changes+=("update-alternatives entry ${name} not managed; skipped (${path})")
    return 0
  fi

  if update-alternatives --set "${name}" "${path}" >/dev/null 2>&1; then
    changes+=("update-alternatives ${name} -> ${path}")
    return 0
  fi

  changes+=("ERROR: failed to set update-alternatives ${name} -> ${path}")
  return 1
}

configure_iptables_legacy_alternatives() {
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
      changes+=("legacy binary ${legacy_path} missing; skipping ${alt}")
      continue
    fi
    if ! set_update_alternative "${alt}" "${legacy_path}"; then
      failures=$((failures + 1))
    fi
  done

  if [[ ${failures} -gt 0 ]]; then
    return 1
  fi
  return 0
}

read_iptables_details() {
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

ensure_iptables_legacy() {
  local variant version path

  if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
    if ! command -v apt-get >/dev/null 2>&1; then
      changes+=("ERROR: iptables binaries missing and apt-get unavailable")
      return 1
    fi
    if ! apt_update_once "iptables"; then
      return 1
    fi
    if DEBIAN_FRONTEND=noninteractive \
      apt-get -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=30 \
      -o Acquire::https::Timeout=30 \
      install -y --no-install-recommends iptables >/dev/null 2>&1; then
      changes+=("installed iptables package to provide legacy backend")
    else
      changes+=("ERROR: failed to install iptables package")
      return 1
    fi
  fi

  if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
    changes+=("ERROR: iptables or ip6tables missing after installation attempt")
    return 1
  fi

  IFS=';' read -r variant version path < <(read_iptables_details)

  if [[ "${variant}" != "legacy" ]]; then
    if ! configure_iptables_legacy_alternatives; then
      return 1
    fi
    IFS=';' read -r variant version path < <(read_iptables_details)
  fi

  LAST_IPTABLES_VARIANT="${variant}"
  LAST_IPTABLES_PATH="${path}"
  LAST_IPTABLES_VERSION="${version}"

  if [[ "${variant}" != "legacy" ]]; then
    changes+=("ERROR: expected iptables legacy backend but detected ${variant}")
    return 1
  fi

  if [[ -n "${path}" ]]; then
    changes+=("iptables binary present at ${path} (variant=${variant} version=${version})")
  else
    changes+=("iptables binary present (variant=${variant} version=${version})")
  fi

  return 0
}

apply_kube_proxy_config() {
  local target_mode="$1"
  local status line
  status=0
  while IFS= read -r line; do
    case "${line}" in
      INFO:*)
        changes+=("${line#INFO: }")
        ;;
      ERROR:*)
        changes+=("ERROR: ${line#ERROR: }")
        ;;
      *)
        changes+=("${line}")
        ;;
    esac
  done < <(kube_proxy::ensure_mode_config "${CONFIG_DIR}" "${target_mode}")
  status=${PIPESTATUS[0]}
  return "${status}"
}

log_kube_proxy_status_once() {
  local mode="$1"
  local nft_status="$2"
  local nft_path="$3"
  local iptables_variant="$4"
  local iptables_path="$5"
  local iptables_version="$6"
  local message
  local state_dir
  local should_write_state=0

  state_dir="$(dirname "${KUBE_PROXY_LOG_STATE}")"

  if [[ "${mode}" == "iptables" ]]; then
    message="kube-proxy mode=${mode} iptables=${iptables_variant}"
    if [[ -n "${iptables_version}" && "${iptables_version}" != "unknown" ]]; then
      message+=" version=${iptables_version}"
    fi
    if [[ -n "${iptables_path}" ]]; then
      message+=" path=${iptables_path}"
    fi
    message+=" nft=${nft_status}"
    if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
      message+=" nft_path=${nft_path}"
    fi
  else
    message="kube-proxy mode=${mode} nft=${nft_status}"
    if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
      message+=" path=${nft_path}"
    fi
  fi

  mkdir -p "${state_dir}" 2>/dev/null || true

  if [[ ! -f "${KUBE_PROXY_LOG_STATE}" ]]; then
    if command -v logger >/dev/null 2>&1; then
      if logger -t sugarkube-k3s-preflight "${message}"; then
        should_write_state=1
      fi
    fi
  else
    should_write_state=1
  fi

  if [[ ${should_write_state} -eq 1 ]]; then
    if [[ "${mode}" == "iptables" ]]; then
      {
        printf 'mode=%s\n' "${mode}"
        printf 'iptables=%s\n' "${iptables_variant}"
        if [[ -n "${iptables_version}" && "${iptables_version}" != "unknown" ]]; then
          printf 'iptables_version=%s\n' "${iptables_version}"
        fi
        if [[ -n "${iptables_path}" ]]; then
          printf 'iptables_path=%s\n' "${iptables_path}"
        fi
        printf 'nft=%s\n' "${nft_status}"
        if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
          printf 'nft_path=%s\n' "${nft_path}"
        fi
      } >"${KUBE_PROXY_LOG_STATE}"
    else
      {
        printf 'mode=%s\n' "${mode}"
        printf 'nft=%s\n' "${nft_status}"
        if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
          printf 'nft_path=%s\n' "${nft_path}"
        fi
      } >"${KUBE_PROXY_LOG_STATE}"
    fi
  fi
}

LAST_KUBE_PROXY_MODE="unknown"
LAST_NFT_STATUS="missing"
LAST_NFT_PATH=""
LAST_IPTABLES_VARIANT="missing"
LAST_IPTABLES_PATH=""
LAST_IPTABLES_VERSION="unknown"

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
    --kube-proxy-mode)
      if [[ $# -lt 2 ]]; then
        echo "--kube-proxy-mode requires an argument" >&2
        exit 1
      fi
      case "${2,,}" in
        nft|nftables)
          DESIRED_KUBE_PROXY_MODE="nftables"
          ;;
        iptables)
          DESIRED_KUBE_PROXY_MODE="iptables"
          ;;
        auto)
          DESIRED_KUBE_PROXY_MODE="auto"
          ;;
        *)
          echo "Unsupported kube-proxy mode: $2" >&2
          exit 1
          ;;
      esac
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--config-dir PATH] [--kube-proxy-mode MODE]" >&2
      exit 1
      ;;
  esac
done

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script with sudo to adjust kernel settings." >&2
  exit 1
fi

changes=()

select_kube_proxy_mode

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
  local expected_mode="${1:-unknown}"
  local configured_mode
  local variant version path

  configured_mode="$(kube_proxy::detect_mode "${CONFIG_DIR}")"

  LAST_KUBE_PROXY_MODE="${configured_mode:-unknown}"
  LAST_NFT_STATUS="missing"
  LAST_NFT_PATH=""
  LAST_IPTABLES_VARIANT="missing"
  LAST_IPTABLES_PATH=""
  LAST_IPTABLES_VERSION="unknown"

  if [[ "${configured_mode}" == "nftables" ]]; then
    if command -v nft >/dev/null 2>&1; then
      LAST_NFT_STATUS="present"
      LAST_NFT_PATH="$(command -v nft)"
      changes+=("kube-proxy mode: nftables (nft binary found)")
    else
      changes+=("ERROR: kube-proxy mode configured as nftables but nft binary not found")
      return 1
    fi
  elif [[ "${configured_mode}" == "iptables" ]]; then
    IFS=';' read -r variant version path < <(read_iptables_details)
    LAST_IPTABLES_VARIANT="${variant}"
    LAST_IPTABLES_PATH="${path}"
    LAST_IPTABLES_VERSION="${version}"

    if [[ "${variant}" == "missing" ]]; then
      changes+=("ERROR: kube-proxy mode configured as iptables but iptables binary not found")
      return 1
    fi

    if [[ "${variant}" == "legacy" ]]; then
      if [[ -n "${path}" ]]; then
        changes+=("kube-proxy mode: iptables (variant=legacy path=${path})")
      else
        changes+=("kube-proxy mode: iptables (variant=legacy)")
      fi
    else
      changes+=("WARNING: kube-proxy mode configured as iptables but binary appears to be ${variant}")
    fi
  else
    changes+=("kube-proxy mode: not configured or unknown")
  fi

  if [[ "${expected_mode}" != "unknown" && "${expected_mode}" != "auto" && \
    "${configured_mode}" != "${expected_mode}" ]]; then
    changes+=("ERROR: kube-proxy mode mismatch (expected ${expected_mode}, found ${configured_mode})")
    return 1
  fi

  if [[ "${LAST_NFT_STATUS}" != "present" ]] && command -v nft >/dev/null 2>&1; then
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

if ! apply_kube_proxy_config "${SELECTED_KUBE_PROXY_MODE}"; then
  preflight_failure=1
fi

if [[ "${SELECTED_KUBE_PROXY_MODE}" == "nftables" ]]; then
  if ! ensure_nft_binary; then
    preflight_failure=1
  fi
elif [[ "${SELECTED_KUBE_PROXY_MODE}" == "iptables" ]]; then
  if ! ensure_iptables_legacy; then
    preflight_failure=1
  fi
fi

# Check kube-proxy mode configuration
if ! check_kube_proxy_mode "${SELECTED_KUBE_PROXY_MODE}"; then
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

log_kube_proxy_status_once \
  "${LAST_KUBE_PROXY_MODE}" \
  "${LAST_NFT_STATUS}" \
  "${LAST_NFT_PATH}" \
  "${LAST_IPTABLES_VARIANT}" \
  "${LAST_IPTABLES_PATH}" \
  "${LAST_IPTABLES_VERSION}"

printf 'k3s preflight adjustments:\n'
for entry in "${changes[@]}"; do
  printf '  - %s\n' "${entry}"
done
