#!/usr/bin/env bash
# detect_target_disk.sh - Identify the first non-SD whole-disk device (prefer NVMe) for cloning.
# Usage: scripts/detect_target_disk.sh
set -euo pipefail

prefer_device() {
  local device="$1"
  if [[ -b "/dev/${device}" ]]; then
    printf '/dev/%s\n' "${device}"
    return 0
  fi
  return 1
}

main() {
  if [[ $(id -u) -ne 0 ]]; then
    echo "This helper should run as root to ensure accurate block device visibility." >&2
  fi

  if prefer_device "nvme0n1"; then
    return 0
  fi

  local candidates
  mapfile -t candidates < <(lsblk -ndo NAME,TYPE | awk '$2=="disk" {print $1}')

  for name in "${candidates[@]}"; do
    if [[ -z "${name}" ]]; then
      continue
    fi
    if [[ "${name}" == mmcblk0* ]]; then
      continue
    fi
    # Skip loopback and mapper devices that mirror the boot media.
    if [[ "${name}" == loop* || "${name}" == mmcblk* ]]; then
      continue
    fi
    if [[ -b "/dev/${name}" ]]; then
      printf '/dev/%s\n' "${name}"
      return 0
    fi
  done

  echo "Unable to detect a target disk that differs from the boot SD card." >&2
  return 1
}

main "$@"
