#!/usr/bin/env bash
# detect_target_disk.sh - Identify the first non-mmcblk0 whole-disk device (prefer NVMe).
# Usage: ./scripts/detect_target_disk.sh
# Prints the detected block device path (e.g. /dev/nvme0n1) or exits non-zero on failure.

set -Eeuo pipefail

PREFERRED_PREFIXES=("nvme" "sd" "vd")
BOOT_DISK="mmcblk0"

list_candidate_disks() {
  lsblk -ndo NAME,TYPE | awk '$2=="disk" {print $1}'
}

disk_has_mounts() {
  local disk="$1"
  lsblk -nr -o NAME,MOUNTPOINT "/dev/${disk}" | awk 'NR>1 && $2!="" {exit 0} END {exit 1}'
}

choose_disk() {
  local candidates sorted=()
  mapfile -t candidates < <(list_candidate_disks)
  if [ "${#candidates[@]}" -eq 0 ]; then
    echo "No disk devices detected" >&2
    return 1
  fi
  for prefix in "${PREFERRED_PREFIXES[@]}"; do
    for disk in "${candidates[@]}"; do
      if [[ "${disk}" == "${BOOT_DISK}"* ]]; then
        continue
      fi
      if disk_has_mounts "${disk}"; then
        continue
      fi
      if [[ "${disk}" == ${prefix}* ]]; then
        echo "${disk}"
        return 0
      fi
    done
  done
  for disk in "${candidates[@]}"; do
    if [[ "${disk}" == "${BOOT_DISK}"* ]]; then
      continue
    fi
    if disk_has_mounts "${disk}"; then
      continue
    fi
    echo "${disk}"
    return 0
  done
  echo "No suitable target disk found" >&2
  return 1
}

main() {
  local disk
  if ! disk=$(choose_disk); then
    echo "Failed to detect target disk" >&2
    exit 1
  fi
  if [[ "${disk}" == "${BOOT_DISK}"* ]]; then
    echo "Detected disk ${disk} matches boot media ${BOOT_DISK}" >&2
    exit 1
  fi
  local dev_path="/dev/${disk}"
  if disk_has_mounts "${disk}"; then
    echo "Detected disk ${dev_path} has mounted partitions; refusing" >&2
    exit 1
  fi
  echo "${dev_path}"
}

main "$@"
