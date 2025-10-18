#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

TARGET="${TARGET:-/dev/nvme0n1}"
ROOT="${TARGET}p2"
BOOT="${TARGET}p1"

sudo umount -R /mnt/clone 2>/dev/null || true
target_base=$(basename "${TARGET}")
if [[ "${target_base}" =~ [0-9]$ ]]; then
  part_glob=(/dev/"${target_base}"p*)
else
  part_glob=(/dev/"${target_base}"[0-9]*)
fi
for p in "${part_glob[@]}"; do
  [[ -e "${p}" ]] || continue
  sudo umount "$p" 2>/dev/null || true
done
sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
sudo mkdir -p /mnt/clone/boot/firmware

if command -v udevadm >/dev/null 2>&1; then
  sudo udevadm settle
fi

# Root mount
if ! sudo mount "$ROOT" /mnt/clone; then
  sudo e2fsck -f -y "$ROOT" || true
  if command -v udevadm >/dev/null 2>&1; then
    sudo udevadm settle
  fi
  sudo mount "$ROOT" /mnt/clone
fi

# Boot mount with recovery
if ! sudo mount "$BOOT" /mnt/clone/boot/firmware; then
  sudo fsck.vfat -a "$BOOT" || true
  if command -v udevadm >/dev/null 2>&1; then
    sudo udevadm settle
  fi
  if ! sudo mount "$BOOT" /mnt/clone/boot/firmware; then
    sudo mkfs.vfat -F 32 -n bootfs "$BOOT"
    if command -v udevadm >/dev/null 2>&1; then
      sudo udevadm settle
    fi
    sudo mount "$BOOT" /mnt/clone/boot/firmware
    sudo rsync -aHAX /boot/firmware/ /mnt/clone/boot/firmware/
  fi
fi

sync
echo "Recovery completed; unmounting."
sudo umount /mnt/clone/boot/firmware || true
sudo umount /mnt/clone || true
