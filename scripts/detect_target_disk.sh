#!/usr/bin/env bash
# detect_target_disk.sh — print the first non-mmcblk0 disk (prefers NVMe) for cloning targets.
# Usage: scripts/detect_target_disk.sh (returns /dev/<disk> or exits non-zero when absent).

set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo --preserve-env "$0" "$@"
fi

mapfile -t disks < <(lsblk -ndo NAME,TYPE | awk '$2=="disk" {print $1}')
if [[ ${#disks[@]} -eq 0 ]]; then
  echo "No disks detected" >&2
  exit 1
fi

root_source=$(findmnt -n -o SOURCE / | sed -E 's/[0-9]+$//' | sed -E 's/p$//')
boot_source=$(findmnt -n -o SOURCE /boot/firmware 2>/dev/null | sed -E 's/[0-9]+$//' | sed -E 's/p$//')

choose_disk=""
for preferred in nvme0n1 nvme1n1; do
  for disk in "${disks[@]}"; do
    if [[ "${disk}" == "${preferred}" ]]; then
      choose_disk="${disk}"
      break 2
    fi
  done
done

if [[ -z "${choose_disk}" ]]; then
  for disk in "${disks[@]}"; do
    if [[ "${disk}" == mmcblk0* ]]; then
      continue
    fi
    choose_disk="${disk}"
    break
  done
fi

if [[ -z "${choose_disk}" ]]; then
  echo "No non-SD disks detected" >&2
  exit 1
fi

if [[ "${choose_disk}" == mmcblk0* ]]; then
  echo "Refusing to operate on boot SD (${choose_disk})" >&2
  exit 1
fi

if [[ -n "${root_source}" && "${choose_disk}" == "${root_source}" ]]; then
  echo "Selected disk ${choose_disk} matches active root (${root_source}); aborting" >&2
  exit 1
fi
if [[ -n "${boot_source}" && "${choose_disk}" == "${boot_source}" ]]; then
  echo "Selected disk ${choose_disk} matches active boot (${boot_source}); aborting" >&2
  exit 1
fi

printf '/dev/%s\n' "${choose_disk}"
