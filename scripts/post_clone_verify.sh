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
  echo "❌ Unable to resolve root (${ROOT_DEV:-unknown}) or boot (${BOOT_DEV:-unknown}) devices." >&2
  exit 1
fi

resolve_parent() {
  local dev="$1" real_dev parent
  real_dev=$(readlink -f "${dev}" 2>/dev/null || true)
  if [[ -z "${real_dev}" ]]; then
    echo ""
    return
  fi
  parent=$(lsblk -no PKNAME "${real_dev}" 2>/dev/null | head -n1 || true)
  if [[ -n "${parent}" ]]; then
    echo "${parent}"
  fi
}

ROOT_PARENT=$(resolve_parent "${ROOT_DEV}")
BOOT_PARENT=$(resolve_parent "${BOOT_DEV}")
if [[ -z "${ROOT_PARENT}" || -z "${BOOT_PARENT}" ]]; then
  echo "❌ Failed to resolve parent disks for root (${ROOT_DEV}) or boot (${BOOT_DEV})." >&2
  exit 1
fi
if [[ "${ROOT_PARENT}" != nvme* || "${BOOT_PARENT}" != nvme* ]]; then
  ROOT_UUID=$(blkid -s UUID -o value "${ROOT_DEV}" 2>/dev/null || true)
  BOOT_UUID=$(blkid -s UUID -o value "${BOOT_DEV}" 2>/dev/null || true)
  echo "❌ Expected NVMe parents but found root=${ROOT_DEV} (parent=${ROOT_PARENT}) [${ROOT_UUID:-no-uuid}]" >&2
  echo "❌ Expected NVMe parents but found boot=${BOOT_DEV} (parent=${BOOT_PARENT}) [${BOOT_UUID:-no-uuid}]" >&2
  exit 1
fi

ROOT_UUID=$(blkid -s UUID -o value "${ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${BOOT_DEV}" 2>/dev/null || true)

echo "✅ NVMe boot verified: /=${ROOT_DEV} (${ROOT_UUID}) parent=${ROOT_PARENT}, /boot/firmware=${BOOT_DEV} (${BOOT_UUID}) parent=${BOOT_PARENT}"
