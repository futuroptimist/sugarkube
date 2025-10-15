#!/usr/bin/env bash
# post_clone_verify.sh - Confirm Raspberry Pi is running from NVMe clone.
# Usage: ./scripts/post_clone_verify.sh
# Verifies / and /boot/firmware are mounted from nvme0n1 partitions and prints UUIDs.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_DIR="${ROOT_DIR}/artifacts/post-clone"
SUMMARY_FILE="${ARTIFACT_DIR}/summary.txt"
mkdir -p "${ARTIFACT_DIR}"

fail() {
  printf '❌ %s\n' "$1" | tee "${SUMMARY_FILE}"
  exit 1
}

main() {
  local root_source boot_source
  root_source=$(findmnt -n -o SOURCE /)
  boot_source=$(findmnt -n -o SOURCE /boot/firmware)
  if [[ "${root_source}" != "/dev/nvme0n1p2" ]]; then
    fail "Root filesystem is ${root_source}, expected /dev/nvme0n1p2"
  fi
  if [[ "${boot_source}" != "/dev/nvme0n1p1" ]]; then
    fail "Boot firmware is ${boot_source}, expected /dev/nvme0n1p1"
  fi
  local root_uuid boot_uuid
  root_uuid=$(blkid -s UUID -o value /dev/nvme0n1p2)
  boot_uuid=$(blkid -s UUID -o value /dev/nvme0n1p1)
  printf '✅ Root=%s Boot=%s\n' "${root_uuid}" "${boot_uuid}" | tee "${SUMMARY_FILE}"
}

main "$@"
