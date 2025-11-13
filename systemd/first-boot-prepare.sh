#!/usr/bin/env bash
# Purpose: Install NVMe migration prerequisites on first boot and capture a log.
# Usage: systemd service helper; run as root.
set -Eeuo pipefail

export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}
LOG_FILE="/var/log/first-boot-prepare.log"
STATE_DIR="/var/lib/sugarkube"
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

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

ensure_package rpi-eeprom
ensure_package ethtool
ensure_package jq
ensure_package parted
ensure_package util-linux
ensure_package curl
ensure_package nftables

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
  done < <(kube_proxy::ensure_nftables_config "/etc/rancher/k3s/config.yaml.d")
  status=${PIPESTATUS[0]}
  return "${status}"
}

log_kube_proxy_mode_once() {
  local config_mode="nftables"
  local nft_status="missing"
  local nft_path=""
  local state_file="${STATE_DIR}/kube-proxy-mode.log"

  if command -v nft >/dev/null 2>&1; then
    nft_status="present"
    nft_path="$(command -v nft)"
  fi

  echo "[first-boot-prepare] kube-proxy mode=${config_mode} nft=${nft_status}${nft_path:+ path=${nft_path}}"

  local should_write_state=0

  if [[ ! -f "${state_file}" ]]; then
    if command -v logger >/dev/null 2>&1; then
      if logger -t sugarkube-first-boot \
        "kube-proxy mode=${config_mode} nft=${nft_status}${nft_path:+ path=${nft_path}}"; then
        should_write_state=1
      fi
    fi
  else
    should_write_state=1
  fi

  if [[ ${should_write_state} -eq 1 ]]; then
    if [[ -n "${nft_path}" ]]; then
      printf 'mode=%s\nnft=%s\nnft_path=%s\n' "${config_mode}" "${nft_status}" "${nft_path}" \
        >"${state_file}"
    else
      printf 'mode=%s\nnft=%s\n' "${config_mode}" "${nft_status}" >"${state_file}"
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
