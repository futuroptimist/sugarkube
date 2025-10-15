#!/usr/bin/env bash
# pi-image-build.sh — provision Pi image dependencies for NVMe cloning and spot checks.
# Usage: run inside the image build chroot/rootfs (idempotent).

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DEST_DIR=/opt/sugarkube

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  rpi-eeprom \
  libraspberrypi-bin \
  ethtool \
  network-manager \
  curl \
  jq \
  parted \
  util-linux \
  wipefs \
  just \
  rsync

install -d -m 0755 "${DEST_DIR}"
rsync -a --delete "${REPO_ROOT}/scripts/" "${DEST_DIR}/scripts/"
rsync -a --delete "${REPO_ROOT}/systemd/" "${DEST_DIR}/systemd/"
install -m 0644 "${REPO_ROOT}/Justfile" "${DEST_DIR}/Justfile"
install -d -m 0755 "${DEST_DIR}/artifacts"

find "${DEST_DIR}/scripts" -type f -name '*.sh' -exec chmod 0755 {} +
chmod 0755 "${DEST_DIR}/systemd/first-boot-prepare.sh"

install -m 0644 "${DEST_DIR}/systemd/first-boot-prepare.service" /etc/systemd/system/first-boot-prepare.service
systemctl enable first-boot-prepare.service

