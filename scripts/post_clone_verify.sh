#!/usr/bin/env bash
# post_clone_verify.sh - Confirm the system is running from the cloned NVMe root and boot partitions.
# Usage: scripts/post_clone_verify.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_DIR="${REPO_ROOT}/artifacts/post-clone"
mkdir -p "${ARTIFACT_DIR}"
LOG_FILE="${ARTIFACT_DIR}/verify.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

root_src="$(findmnt -n -o SOURCE / || true)"
boot_src="$(findmnt -n -o SOURCE /boot/firmware || true)"

if [[ -z "${root_src}" || -z "${boot_src}" ]]; then
  echo "[post-clone] Unable to determine current root or boot devices." >&2
  exit 1
fi

expected_root_prefix="/dev/nvme0n1p2"
expected_boot_prefix="/dev/nvme0n1p1"

if [[ "${TARGET:-}" =~ ^/dev/ ]]; then
  expected_root_prefix="${TARGET}p2"
  expected_boot_prefix="${TARGET}p1"
fi

status=0
if [[ "${root_src}" != "${expected_root_prefix}" ]]; then
  echo "[post-clone] Root filesystem is ${root_src}, expected ${expected_root_prefix}" >&2
  status=1
else
  echo "[post-clone] Root filesystem verified on ${root_src}."
fi

if [[ "${boot_src}" != "${expected_boot_prefix}" ]]; then
  echo "[post-clone] Boot partition is ${boot_src}, expected ${expected_boot_prefix}" >&2
  status=1
else
  echo "[post-clone] Boot partition verified on ${boot_src}."
fi

if [[ ${status} -ne 0 ]]; then
  exit ${status}
fi

echo "[post-clone] System is running entirely from NVMe (${root_src} / ${boot_src})."
