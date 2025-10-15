#!/usr/bin/env bash
# post_clone_verify.sh — confirm the system booted from NVMe after cloning.
# Usage: just post-clone-verify (safe anytime after reboot).

set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo --preserve-env "$0" "$@"
fi

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_ROOT_DIR="${ARTIFACT_ROOT:-${REPO_ROOT}/artifacts}"
ARTIFACT_DIR="${ARTIFACT_ROOT_DIR}/post-clone"
LOG_FILE="${ARTIFACT_DIR}/verify.log"
mkdir -p "${ARTIFACT_DIR}"
touch "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

df -h >"${ARTIFACT_DIR}/df-h.txt"
lsblk -o NAME,TYPE,MOUNTPOINT >"${ARTIFACT_DIR}/lsblk.txt"

root_source=$(findmnt -n -o SOURCE /)
boot_source=$(findmnt -n -o SOURCE /boot/firmware 2>/dev/null || true)

status=0
if [[ "${root_source}" =~ ^/dev/nvme.+p2$ ]]; then
  echo "✅ Root filesystem on ${root_source}"
else
  echo "❌ Root filesystem not on NVMe (found ${root_source:-unknown})"
  status=1
fi

if [[ "${boot_source}" =~ ^/dev/nvme.+p1$ ]]; then
  echo "✅ Boot firmware on ${boot_source}"
else
  echo "❌ /boot/firmware not on NVMe (found ${boot_source:-unknown})"
  status=1
fi

if [[ ${status} -ne 0 ]]; then
  exit ${status}
fi

echo "NVMe clone verified: root=${root_source}, boot=${boot_source}"
