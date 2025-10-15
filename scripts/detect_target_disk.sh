#!/usr/bin/env bash
# Purpose: Detect the first non-SD whole-disk device suitable as an NVMe/USB clone target.
# Usage: scripts/detect_target_disk.sh
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
mkdir -p "${ARTIFACT_DIR}"
LOG_FILE="${ARTIFACT_DIR}/detect-target-disk.log"
exec > >(tee "${LOG_FILE}") 2>&1

if [[ ${EUID} -ne 0 ]]; then
  echo "This script requires root privileges." >&2
  exit 1
fi

get_root_disk() {
  local root_source root_device parent
  root_source=$(findmnt -no SOURCE /)
  if [[ -z "${root_source}" ]]; then
    echo "Unable to determine root filesystem source" >&2
    return 1
  fi
  if [[ "${root_source}" =~ ^/dev/ ]]; then
    root_device="${root_source}"
  elif [[ "${root_source}" =~ ^UUID= ]]; then
    root_device=$(blkid -U "${root_source#UUID=}")
  elif [[ "${root_source}" =~ ^PARTUUID= ]]; then
    root_device=$(blkid -o device -t "PARTUUID=${root_source#PARTUUID=}")
  else
    echo "Unsupported root source format: ${root_source}" >&2
    return 1
  fi
  if [[ -z "${root_device}" ]]; then
    echo "Unable to resolve root device from ${root_source}" >&2
    return 1
  fi
  parent=$(lsblk -no PKNAME "${root_device}" 2>/dev/null || true)
  if [[ -n "${parent}" ]]; then
    echo "${parent}"
    return 0
  fi
  parent=${root_device#/dev/}
  parent=${parent%%[0-9p]*}
  echo "${parent}"
}

ROOT_DISK=$(get_root_disk)
if [[ -z "${ROOT_DISK}" ]]; then
  echo "Failed to detect the root disk backing /" >&2
  exit 1
fi

declare -a CANDIDATES=()
while read -r name type; do
  if [[ "${type}" != "disk" ]]; then
    continue
  fi
  if [[ "${name}" == "${ROOT_DISK}" ]]; then
    continue
  fi
  CANDIDATES+=("${name}")
done < <(lsblk -ndo NAME,TYPE)

preferred=""
for disk in "${CANDIDATES[@]}"; do
  if [[ "${disk}" == nvme0n1 ]]; then
    preferred="${disk}"
    break
  fi
  if [[ -z "${preferred}" ]]; then
    preferred="${disk}"
  fi
done

if [[ -z "${preferred}" ]]; then
  echo "No clone target disks detected (only found root disk ${ROOT_DISK})." >&2
  exit 1
fi

target_path="/dev/${preferred}"
if [[ "${preferred}" == mmcblk0 ]]; then
  echo "Safety check triggered: detected disk resolves to boot SD (${target_path})." >&2
  exit 1
fi

if [[ "${preferred}" == "${ROOT_DISK}" ]]; then
  echo "Safety check triggered: target disk ${target_path} matches root disk." >&2
  exit 1
fi

if [[ ! -b "${target_path}" ]]; then
  echo "Detected target disk ${target_path} is not a block device." >&2
  exit 1
fi

echo "${target_path}"
