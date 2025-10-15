#!/usr/bin/env bash
# Purpose: Verify the system is running from the NVMe clone after reboot.
# Usage: sudo ./scripts/post_clone_verify.sh
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
LOG_FILE="${ARTIFACT_DIR}/post-clone-verify.log"
mkdir -p "${ARTIFACT_DIR}"
exec > >(tee "${LOG_FILE}") 2>&1

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo to inspect block devices." >&2
  exit 1
fi

resolve_mount() {
  local target="$1" src
  src=$(findmnt -no SOURCE "${target}" 2>/dev/null || true)
  if [[ -z "${src}" ]]; then
    echo ""
    return
  fi
  if [[ "${src}" =~ ^/dev/ ]]; then
    echo "${src}"
  elif [[ "${src}" =~ ^UUID= ]]; then
    blkid -U "${src#UUID=}"
  elif [[ "${src}" =~ ^PARTUUID= ]]; then
    blkid -o device -t "PARTUUID=${src#PARTUUID=}"
  else
    echo ""
  fi
}

ROOT_DEV=$(resolve_mount /)
BOOT_DEV=$(resolve_mount /boot/firmware)
if [[ "${ROOT_DEV}" != /dev/nvme0n1p2 ]]; then
  echo "❌ Root filesystem is on ${ROOT_DEV:-unknown}; expected /dev/nvme0n1p2." >&2
  exit 1
fi
if [[ "${BOOT_DEV}" != /dev/nvme0n1p1 ]]; then
  echo "❌ Boot filesystem is on ${BOOT_DEV:-unknown}; expected /dev/nvme0n1p1." >&2
  exit 1
fi

ROOT_UUID=$(blkid -s UUID -o value "${ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${BOOT_DEV}" 2>/dev/null || true)

echo "✅ NVMe boot verified: /=${ROOT_DEV} (${ROOT_UUID}), /boot/firmware=${BOOT_DEV} (${BOOT_UUID})"
