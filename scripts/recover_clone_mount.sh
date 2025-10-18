#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

TARGET="${TARGET:-/dev/nvme0n1}"
ROOT="${TARGET}p2"
BOOT="${TARGET}p1"

sudo umount -R /mnt/clone 2>/dev/null || true
shopt -s nullglob
for p in /dev/"$(basename "${TARGET}")"p*; do
  sudo umount "$p" 2>/dev/null || true
done
shopt -u nullglob
sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
sudo mkdir -p /mnt/clone/boot/firmware

sudo udevadm settle || true

if ! sudo mount "${ROOT}" /mnt/clone; then
  sudo e2fsck -f -y "${ROOT}" || true
  sudo udevadm settle || true
  sudo mount "${ROOT}" /mnt/clone
fi

if ! sudo mount "${BOOT}" /mnt/clone/boot/firmware; then
  sudo fsck.vfat -a "${BOOT}" || true
  sudo udevadm settle || true
  if ! sudo mount "${BOOT}" /mnt/clone/boot/firmware; then
    sudo mkfs.vfat -F 32 -n bootfs "${BOOT}"
    sudo udevadm settle || true
    sudo mount "${BOOT}" /mnt/clone/boot/firmware
    sudo rsync -aHAX /boot/firmware/ /mnt/clone/boot/firmware/
  fi
fi

sync
echo "Recovery completed; unmounting."
sudo umount /mnt/clone/boot/firmware || true
sudo umount /mnt/clone || true
