#!/usr/bin/env bash
# Purpose: Install NVMe migration prerequisites on first boot and capture a log.
# Usage: systemd service helper; run as root.
set -Eeuo pipefail

export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}
LOG_FILE="/var/log/first-boot-prepare.log"
STATE_DIR="/var/lib/sugarkube"
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
K3S_CONFIG_DIR="/etc/rancher/k3s/config.yaml.d"
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

K3S_PREFLIGHT="/opt/sugarkube/k3s_preflight.sh"
if [[ -x "${K3S_PREFLIGHT}" ]]; then
  echo "[first-boot-prepare] running k3s preflight"
  if "${K3S_PREFLIGHT}" --config-dir "${K3S_CONFIG_DIR}"; then
    echo "[first-boot-prepare] k3s preflight completed"
  else
    preflight_exit=$?
    echo "[first-boot-prepare] warning: k3s preflight exited with ${preflight_exit}"
  fi
else
  echo "[first-boot-prepare] k3s preflight helper missing at ${K3S_PREFLIGHT}"
fi

SET_NVME_BOOT=${SET_NVME_BOOT:-1}
NVME_SCRIPT="/usr/local/sbin/eeprom-nvme-first"
if [[ "${SET_NVME_BOOT}" == "1" && -x "${NVME_SCRIPT}" ]]; then
  echo "[first-boot-prepare] ensuring EEPROM prefers NVMe"
  "${NVME_SCRIPT}" || echo "[first-boot-prepare] warning: EEPROM helper exited with $?."
fi

touch "${STATE_FILE}"
echo "[first-boot-prepare] completed"
