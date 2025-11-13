#!/usr/bin/env bash
# Purpose: Install NVMe migration prerequisites on first boot and capture a log.
# Usage: systemd service helper; run as root.
set -Eeuo pipefail

export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}
LOG_FILE="/var/log/first-boot-prepare.log"
STATE_DIR="/var/lib/sugarkube"
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CONFIG_DIR="/etc/rancher/k3s/config.yaml.d"

DESIRED_KUBE_PROXY_MODE="auto"
SELECTED_KUBE_PROXY_MODE="unknown"
KUBE_PROXY_MODE_SOURCE="default"
LAST_IPTABLES_VARIANT="missing"
LAST_IPTABLES_PATH=""
LAST_IPTABLES_VERSION="unknown"
LAST_NFT_STATUS="missing"
LAST_NFT_PATH=""

# Source shared kube-proxy helpers
KUBE_PROXY_LIB="/usr/local/lib/sugarkube/kube_proxy.sh"
if [[ -f "${KUBE_PROXY_LIB}" ]]; then
  # shellcheck disable=SC1091
  source "${KUBE_PROXY_LIB}"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  ALT_LIB="${SCRIPT_DIR}/../scripts/lib/kube_proxy.sh"
  if [[ -f "${ALT_LIB}" ]]; then
    # shellcheck disable=SC1091
    source "${ALT_LIB}"
  else
    echo "[first-boot-prepare] ERROR: kube_proxy.sh library not found"
    exit 1
  fi
fi

mkdir -p "${STATE_DIR}" "$(dirname "${LOG_FILE}")"
exec >>"${LOG_FILE}" 2>&1

echo "[first-boot-prepare] $(date --iso-8601=seconds) starting"

if [[ ${EUID} -ne 0 ]]; then
  echo "[first-boot-prepare] must run as root"
  exit 1
fi

if [[ -f "${STATE_FILE}" ]]; then
  echo "[first-boot-prepare] already completed; exiting"
  exit 0
fi

APT_UPDATED=0
apt_update_once() {
  if [[ ${APT_UPDATED} -eq 0 ]]; then
    echo "[first-boot-prepare] apt-get update"
    apt-get -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=30 \
      -o Acquire::https::Timeout=30 \
      update
    APT_UPDATED=1
  fi
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
  local override

  if [[ -n "${FIRST_BOOT_KUBE_PROXY_MODE:-}" ]]; then
    override="$(normalize_kube_proxy_mode "${FIRST_BOOT_KUBE_PROXY_MODE}")"
    if [[ "${override}" != "unknown" ]]; then
      desired="${override}"
    fi
  fi

  env_mode="$(normalize_kube_proxy_mode "${K3S_KUBE_PROXY_MODE:-}")"

  if [[ "${desired}" != "auto" && "${desired}" != "unknown" ]]; then
    SELECTED_KUBE_PROXY_MODE="${desired}"
    KUBE_PROXY_MODE_SOURCE="override"
  elif [[ "${env_mode}" == "nftables" || "${env_mode}" == "iptables" ]]; then
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

  echo "[first-boot-prepare] kube-proxy backend selection: ${SELECTED_KUBE_PROXY_MODE} (source=${KUBE_PROXY_MODE_SOURCE})"
}

ensure_package() {
  local pkg="$1"
  if dpkg -s "${pkg}" >/dev/null 2>&1; then
    echo "[first-boot-prepare] package ${pkg} already present"
    return
  fi
  apt_update_once
  echo "[first-boot-prepare] installing ${pkg}"
  apt-get -o Acquire::Retries=5 \
    -o Acquire::http::Timeout=30 \
    -o Acquire::https::Timeout=30 \
    install -y --no-install-recommends "${pkg}"
}

set_update_alternative() {
  local name="$1"
  local path="$2"

  if ! command -v update-alternatives >/dev/null 2>&1; then
    echo "[first-boot-prepare] ERROR: update-alternatives unavailable for ${name}"
    return 1
  fi

  if ! update-alternatives --query "${name}" >/dev/null 2>&1; then
    echo "[first-boot-prepare] update-alternatives entry ${name} not managed; skipped (${path})"
    return 0
  fi

  if update-alternatives --set "${name}" "${path}" >/dev/null 2>&1; then
    echo "[first-boot-prepare] update-alternatives ${name} -> ${path}"
    return 0
  fi

  echo "[first-boot-prepare] ERROR: failed to set update-alternatives ${name} -> ${path}"
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
      echo "[first-boot-prepare] legacy binary ${legacy_path} missing; skipping ${alt}"
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
    apt_update_once
    echo "[first-boot-prepare] installing iptables"
    apt-get -o Acquire::Retries=5 \
      -o Acquire::http::Timeout=30 \
      -o Acquire::https::Timeout=30 \
      install -y --no-install-recommends iptables
  fi

  if ! command -v iptables >/dev/null 2>&1 || ! command -v ip6tables >/dev/null 2>&1; then
    echo "[first-boot-prepare] ERROR: iptables or ip6tables missing after installation"
    return 1
  fi

  IFS=';' read -r variant version path < <(read_iptables_details)

  if [[ "${variant}" != "legacy" ]]; then
    if ! configure_iptables_legacy_alternatives; then
      echo "[first-boot-prepare] ERROR: failed to switch iptables alternatives to legacy"
      return 1
    fi
    IFS=';' read -r variant version path < <(read_iptables_details)
  fi

  LAST_IPTABLES_VARIANT="${variant}"
  LAST_IPTABLES_PATH="${path}"
  LAST_IPTABLES_VERSION="${version}"

  if [[ "${variant}" != "legacy" ]]; then
    echo "[first-boot-prepare] ERROR: expected iptables legacy backend but detected ${variant}"
    return 1
  fi

  if [[ -n "${path}" ]]; then
    echo "[first-boot-prepare] iptables binary ${path} variant=${variant} version=${version}"
  else
    echo "[first-boot-prepare] iptables binary variant=${variant} version=${version}"
  fi

  return 0
}

select_kube_proxy_mode

ensure_package rpi-eeprom
ensure_package ethtool
ensure_package jq
ensure_package parted
ensure_package util-linux
ensure_package curl

if [[ "${SELECTED_KUBE_PROXY_MODE}" == "nftables" ]]; then
  ensure_package nftables
else
  if ! ensure_iptables_legacy; then
    echo "[first-boot-prepare] ERROR: failed to provision iptables legacy backend"
    exit 1
  fi
fi

if ! command -v vcgencmd >/dev/null 2>&1; then
  ensure_package libraspberrypi-bin
fi

if ! command -v rpi-clone >/dev/null 2>&1; then
  echo "[first-boot-prepare] installing rpi-clone"
  curl -fsSL https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install | bash
fi

ensure_kube_proxy_config() {
  local status line
  status=0
  while IFS= read -r line; do
    case "${line}" in
      INFO:*)
        echo "[first-boot-prepare] ${line#INFO: }"
        ;;
      ERROR:*)
        echo "[first-boot-prepare] ERROR: ${line#ERROR: }"
        ;;
      *)
        echo "[first-boot-prepare] ${line}"
        ;;
    esac
  done < <(kube_proxy::ensure_mode_config "${CONFIG_DIR}" "${SELECTED_KUBE_PROXY_MODE}")
  status=${PIPESTATUS[0]}
  return "${status}"
}

log_kube_proxy_mode_once() {
  local config_mode
  local nft_status="missing"
  local nft_path=""
  local iptables_variant="${LAST_IPTABLES_VARIANT}"
  local iptables_path="${LAST_IPTABLES_PATH}"
  local iptables_version="${LAST_IPTABLES_VERSION}"
  local state_file="${STATE_DIR}/kube-proxy-mode.log"
  local message
  local should_write_state=0

  config_mode="$(kube_proxy::detect_mode "${CONFIG_DIR}")"
  if [[ "${config_mode}" == "unknown" ]]; then
    config_mode="${SELECTED_KUBE_PROXY_MODE}"
  fi

  if command -v nft >/dev/null 2>&1; then
    nft_status="present"
    nft_path="$(command -v nft)"
  fi

  if [[ "${config_mode}" == "iptables" ]]; then
    IFS=';' read -r iptables_variant iptables_version iptables_path < <(read_iptables_details)
  fi

  if [[ "${config_mode}" == "iptables" ]]; then
    message="kube-proxy mode=${config_mode} iptables=${iptables_variant}"
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
    message="kube-proxy mode=${config_mode} nft=${nft_status}"
    if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
      message+=" path=${nft_path}"
    fi
  fi

  echo "[first-boot-prepare] ${message}"

  if [[ ! -f "${state_file}" ]]; then
    if command -v logger >/dev/null 2>&1; then
      if logger -t sugarkube-first-boot "${message}"; then
        should_write_state=1
      fi
    fi
  else
    should_write_state=1
  fi

  if [[ ${should_write_state} -eq 1 ]]; then
    if [[ "${config_mode}" == "iptables" ]]; then
      {
        printf 'mode=%s\n' "${config_mode}"
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
      } >"${state_file}"
    else
      {
        printf 'mode=%s\n' "${config_mode}"
        printf 'nft=%s\n' "${nft_status}"
        if [[ "${nft_status}" == "present" && -n "${nft_path}" ]]; then
          printf 'nft_path=%s\n' "${nft_path}"
        fi
      } >"${state_file}"
    fi
  fi
}

ensure_kube_proxy_config
log_kube_proxy_mode_once

SET_NVME_BOOT=${SET_NVME_BOOT:-1}
NVME_SCRIPT="/usr/local/sbin/eeprom-nvme-first"
if [[ "${SET_NVME_BOOT}" == "1" && -x "${NVME_SCRIPT}" ]]; then
  echo "[first-boot-prepare] ensuring EEPROM prefers NVMe"
  "${NVME_SCRIPT}" || echo "[first-boot-prepare] warning: EEPROM helper exited with $?."
fi

touch "${STATE_FILE}"
echo "[first-boot-prepare] completed"
