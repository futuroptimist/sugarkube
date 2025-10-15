#!/usr/bin/env bash
# clone_to_nvme.sh — unattended SD→NVMe clone with Bookworm-aware fixups and safety rails.
# Usage: sudo just clone-ssd TARGET=/dev/nvme0n1 WIPE=1 (TARGET autodetected when unset).

set -Eeuo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  exec sudo --preserve-env=TARGET,WIPE "$0" "$@"
fi

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ARTIFACT_ROOT_DIR="${ARTIFACT_ROOT:-${REPO_ROOT}/artifacts}"
ARTIFACT_DIR="${ARTIFACT_ROOT_DIR}/clone"
LOG_FILE="${ARTIFACT_DIR}/clone.log"
mkdir -p "${ARTIFACT_DIR}"
touch "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1

TARGET_DEVICE="${TARGET:-}"
WIPE_TARGET="${WIPE:-0}"

if [[ -z "${TARGET_DEVICE}" ]]; then
  TARGET_DEVICE="$(${SCRIPT_DIR}/detect_target_disk.sh)"
fi

if [[ ! -b "${TARGET_DEVICE}" ]]; then
  echo "Target ${TARGET_DEVICE} is not a block device" >&2
  exit 1
fi

if [[ "${TARGET_DEVICE}" =~ mmcblk0 ]]; then
  echo "Refusing to overwrite mmcblk0" >&2
  exit 1
fi

source_used=$(df -B1 --output=used / | tail -n1 | tr -d ' ')
if [[ -z "${source_used}" ]]; then
  echo "Unable to determine source filesystem usage" >&2
  exit 1
fi

target_size=$(lsblk -bno SIZE "${TARGET_DEVICE}")
if [[ -z "${target_size}" ]]; then
  echo "Unable to determine target size for ${TARGET_DEVICE}" >&2
  exit 1
fi
if (( target_size < source_used )); then
  echo "Target ${TARGET_DEVICE} (${target_size} bytes) smaller than source usage (${source_used} bytes)" >&2
  exit 1
fi

mounted_parts=$(lsblk -nr -o NAME,MOUNTPOINT "${TARGET_DEVICE}" | awk '$2!="" {print $1"=" $2}')
if [[ -n "${mounted_parts}" ]]; then
  echo "Target has mounted partitions: ${mounted_parts}" >&2
  exit 1
fi

if ! command -v rpi-clone >/dev/null 2>&1; then
  echo "Installing geerlingguy/rpi-clone" | tee "${ARTIFACT_DIR}/install.log"
  curl -fsSL https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install | bash >/tmp/rpi-clone-install.log 2>&1
  cat /tmp/rpi-clone-install.log >>"${ARTIFACT_DIR}/install.log"
fi

if [[ "${WIPE_TARGET}" == "1" ]]; then
  echo "WIPE=1 → clearing signatures on ${TARGET_DEVICE}"
  wipefs --all --force "${TARGET_DEVICE}"
fi

target_name=$(basename "${TARGET_DEVICE}")
clone_output_file="${ARTIFACT_DIR}/rpi-clone.txt"
if ! rpi-clone -f -u "${target_name}" | tee "${clone_output_file}"; then
  echo "rpi-clone failed" >&2
  exit 1
fi

clone_mount=/mnt/clone
boot_mount="${clone_mount}/boot/firmware"
if [[ ! -d "${boot_mount}" ]]; then
  boot_mount="${clone_mount}/boot"
fi

if [[ -b "${TARGET_DEVICE}p1" ]]; then
  partition_suffix="p"
else
  partition_suffix=""
fi

boot_part="${TARGET_DEVICE}${partition_suffix}1"
root_part="${TARGET_DEVICE}${partition_suffix}2"

get_uuid() {
  local device="$1" field="$2"
  blkid -s "${field}" -o value "${device}" 2>/dev/null || true
}

target_root_identifier=$(get_uuid "${root_part}" PARTUUID)
[[ -z "${target_root_identifier}" ]] && target_root_identifier=$(get_uuid "${root_part}" UUID)

target_boot_identifier=$(get_uuid "${boot_part}" UUID)
[[ -z "${target_boot_identifier}" ]] && target_boot_identifier=$(get_uuid "${boot_part}" PARTUUID)

root_ref="${target_root_identifier}"
if [[ -n "${root_ref}" ]]; then
  if [[ "${root_ref}" != UUID=* && "${root_ref}" != PARTUUID=* ]]; then
    if [[ ${#root_ref} -eq 36 ]]; then
      root_ref="UUID=${root_ref}"
    else
      root_ref="PARTUUID=${root_ref}"
    fi
  fi
fi

boot_ref="${target_boot_identifier}"
if [[ -n "${boot_ref}" ]]; then
  if [[ "${boot_ref}" != UUID=* && "${boot_ref}" != PARTUUID=* ]]; then
    if [[ ${#boot_ref} -eq 8 ]]; then
      boot_ref="UUID=${boot_ref}"
    else
      boot_ref="PARTUUID=${boot_ref}"
    fi
  fi
fi

cmdline_file="${boot_mount}/cmdline.txt"
if [[ -f "${cmdline_file}" && -n "${root_ref}" ]]; then
  python3 - <<'PY' "${cmdline_file}" "${root_ref}"
import sys
from pathlib import Path

path = Path(sys.argv[1])
root_arg = sys.argv[2]
content = path.read_text().strip()
parts = content.split()
for idx, token in enumerate(parts):
    if token.startswith("root="):
        parts[idx] = f"root={root_arg}"
        break
else:
    parts.append(f"root={root_arg}")
path.write_text(" ".join(parts) + "\n")
PY
fi

fstab_file="${clone_mount}/etc/fstab"
if [[ -f "${fstab_file}" ]]; then
  python3 - <<'PY' "${fstab_file}" "${root_ref}" "${boot_ref}"
import sys
from pathlib import Path

fstab = Path(sys.argv[1])
root_arg = sys.argv[2]
boot_arg = sys.argv[3]
lines = fstab.read_text().splitlines()
updated = []
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        updated.append(line)
        continue
    parts = stripped.split()
    if len(parts) < 2:
        updated.append(line)
        continue
    mount = parts[1]
    if mount == '/':
        if root_arg:
            parts[0] = root_arg
        updated.append("\t".join(parts))
        continue
    if mount in {'/boot/firmware', '/boot'}:
        if boot_arg:
            parts[0] = boot_arg
        updated.append("\t".join(parts))
        continue
    updated.append(line)
fstab.write_text("\n".join(updated) + "\n")
PY
fi

bytes_used="${source_used}"
printf 'Clone complete → %s (root %s, boot %s) ~%s bytes cloned\n' "${TARGET_DEVICE}" "${root_ref:-unknown}" "${boot_ref:-unknown}" "${bytes_used}"
printf '%s\n' "${TARGET_DEVICE}" >"${ARTIFACT_DIR}/target.txt"
