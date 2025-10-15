#!/usr/bin/env bash
# first-boot-prepare.sh — install NVMe migration dependencies during first boot.
# Usage: systemd one-shot service (idempotent; logs to /var/log/first-boot-prepare.log).

set -Eeuo pipefail

LOG_FILE=/var/log/first-boot-prepare.log
mkdir -p /var/log
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "[first-boot] starting $(date --iso-8601=seconds)"

STATE_DIR=/var/lib/sugarkube
STATE_FILE="${STATE_DIR}/first-boot-prepare.done"
REPO_DIR=/opt/sugarkube

mkdir -p "${STATE_DIR}"

if [[ -f "${STATE_FILE}" ]]; then
  echo "[first-boot] already complete"
  exit 0
fi

if ! command -v rpi-eeprom-update >/dev/null 2>&1; then
  echo "[first-boot] installing rpi-eeprom"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y rpi-eeprom
fi

if ! command -v rpi-clone >/dev/null 2>&1; then
  echo "[first-boot] installing geerlingguy/rpi-clone"
  curl -fsSL https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install | bash
fi

if [[ -x "${REPO_DIR}/scripts/eeprom_nvme_first.sh" ]]; then
  echo "[first-boot] ensuring EEPROM NVMe boot order"
  "${REPO_DIR}/scripts/eeprom_nvme_first.sh" || true
fi

if [[ -x "${REPO_DIR}/scripts/spot_check.sh" ]]; then
  echo "[first-boot] priming spot-check artifacts"
  ARTIFACT_ROOT="${REPO_DIR}/artifacts" "${REPO_DIR}/scripts/spot_check.sh" >/dev/null 2>&1 || true
fi

touch "${STATE_FILE}"
echo "[first-boot] complete"
