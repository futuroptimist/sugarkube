#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

TARGET="${TARGET:-/dev/nvme0n1}"
ROOT="${TARGET}p2"
BOOT="${TARGET}p1"
target_base=$(basename "${TARGET}")

shopt -s nullglob

sudo umount -R /mnt/clone 2>/dev/null || true
for p in /dev/"${target_base}"p* /dev/"${target_base}"[0-9]*; do
  sudo umount "$p" 2>/dev/null || true
done
sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
sudo mkdir -p /mnt/clone/boot/firmware

sudo udevadm settle

# Root mount
if ! sudo mount "${ROOT}" /mnt/clone; then
  sudo e2fsck -f -y "${ROOT}" || true
  sudo udevadm settle
  sudo mount "${ROOT}" /mnt/clone
fi

# Boot mount with recovery
if ! sudo mount "${BOOT}" /mnt/clone/boot/firmware; then
  sudo fsck.vfat -a "${BOOT}" || true
  sudo udevadm settle
  if ! sudo mount "${BOOT}" /mnt/clone/boot/firmware; then
    sudo mkfs.vfat -F 32 -n bootfs "${BOOT}"
    sudo udevadm settle
    sleep 1
    sudo mount "${BOOT}" /mnt/clone/boot/firmware
    sudo rsync -aHAX /boot/firmware/ /mnt/clone/boot/firmware/
  fi
fi

sync
echo "Recovery completed; unmounting."
sudo umount /mnt/clone/boot/firmware || true
sudo umount /mnt/clone || true
