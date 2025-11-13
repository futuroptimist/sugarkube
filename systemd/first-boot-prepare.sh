#!/usr/bin/env bash
# Purpose: Install NVMe migration prerequisites on first boot and capture a log.
# Usage: systemd service helper; run as root.
set -Eeuo pipefail

export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}
LOG_FILE="/var/log/first-boot-prepare.log"
STATE_DIR="/var/lib/sugarkube"
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

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
  local config_dir="/etc/rancher/k3s/config.yaml.d"
  local config_path="${config_dir}/10-kube-proxy.yaml"
  local desired=$'kube-proxy-arg:\n  - proxy-mode=nftables\n'
  local temp_file

  if [[ ! -d "${config_dir}" ]]; then
    echo "[first-boot-prepare] creating ${config_dir}"
    mkdir -p "${config_dir}"
  fi

  temp_file="$(mktemp)"
  printf '%s' "${desired}" >"${temp_file}"

  if [[ ! -f "${config_path}" ]] || ! cmp -s "${temp_file}" "${config_path}"; then
    echo "[first-boot-prepare] writing kube-proxy nftables config"
    install -m 0644 "${temp_file}" "${config_path}"
  else
    echo "[first-boot-prepare] kube-proxy nftables config already present"
  fi

  rm -f "${temp_file}"
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

  if [[ ! -f "${state_file}" ]]; then
    if command -v logger >/dev/null 2>&1; then
      logger -t sugarkube-first-boot \
        "kube-proxy mode=${config_mode} nft=${nft_status}${nft_path:+ path=${nft_path}}"
    fi
  fi

  if [[ -n "${nft_path}" ]]; then
    printf 'mode=%s\nnft=%s\nnft_path=%s\n' "${config_mode}" "${nft_status}" "${nft_path}" \
      >"${state_file}"
  else
    printf 'mode=%s\nnft=%s\n' "${config_mode}" "${nft_status}" >"${state_file}"
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
