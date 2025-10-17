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
if [[ -z "${ROOT_DEV}" || -z "${BOOT_DEV}" ]]; then
  echo "❌ Unable to resolve root (${ROOT_DEV:-unknown}) or boot (${BOOT_DEV:-unknown}) mount." >&2
  exit 1
fi

ROOT_PARENT=$(lsblk -no PKNAME "$(readlink -f "${ROOT_DEV}")" 2>/dev/null || true)
BOOT_PARENT=$(lsblk -no PKNAME "$(readlink -f "${BOOT_DEV}")" 2>/dev/null || true)
if [[ -z "${ROOT_PARENT}" || -z "${BOOT_PARENT}" ]]; then
  echo "❌ Unable to determine parent disks for ${ROOT_DEV} (${ROOT_PARENT:-unknown}) and ${BOOT_DEV} (${BOOT_PARENT:-unknown})." >&2
  exit 1
fi

if [[ "${ROOT_PARENT}" != nvme* || "${BOOT_PARENT}" != nvme* ]]; then
  ROOT_UUID=$(blkid -s UUID -o value "${ROOT_DEV}" 2>/dev/null || true)
  BOOT_UUID=$(blkid -s UUID -o value "${BOOT_DEV}" 2>/dev/null || true)
  echo "❌ Expected NVMe parents. root=${ROOT_DEV} (${ROOT_UUID:-no-uuid}) [parent=/dev/${ROOT_PARENT}], boot=${BOOT_DEV} (${BOOT_UUID:-no-uuid}) [parent=/dev/${BOOT_PARENT}]" >&2
  exit 1
fi

ROOT_UUID=$(blkid -s UUID -o value "${ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${BOOT_DEV}" 2>/dev/null || true)

echo "✅ NVMe boot verified: /=${ROOT_DEV} (${ROOT_UUID}), /boot/firmware=${BOOT_DEV} (${BOOT_UUID}); parents=/dev/${ROOT_PARENT}, /dev/${BOOT_PARENT}"
