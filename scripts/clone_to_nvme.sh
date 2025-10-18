#!/usr/bin/env bash
# Purpose: Clone the active SD card to an attached NVMe/USB disk and fix Bookworm boot configs.
# Usage: TARGET=/dev/nvme0n1 WIPE=1 sudo --preserve-env=TARGET,WIPE scripts/clone_to_nvme.sh
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
LOG_FILE="${ARTIFACT_DIR}/clone-to-nvme.log"
mkdir -p "${ARTIFACT_DIR}"
exec > >(tee "${LOG_FILE}") 2>&1

log() {
  echo "[clone] $*"
}

TARGET="${TARGET:-/dev/nvme0n1}"
WIPE="${WIPE:-0}"
ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"

if [[ "${ALLOW_NON_ROOT}" != "1" && ${EUID} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    log "Re-executing with sudo while preserving TARGET and WIPE"
    exec sudo --preserve-env=TARGET,WIPE,ALLOW_NON_ROOT "$0" "$@"
  fi
  echo "This script requires root privileges." >&2
  exit 1
fi

require_command() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command '${cmd}' not found." >&2
    exit 1
  fi
}

require_command findmnt
require_command lsblk
require_command blkid
require_command rsync

if [[ -z "${TARGET}" ]]; then
  echo "TARGET device not specified." >&2
  exit 1
fi

if [[ ! -b "${TARGET}" ]]; then
  if [[ "${ALLOW_FAKE_BLOCK:-0}" == "1" ]]; then
    log "Target ${TARGET} is not a block device, continuing due to ALLOW_FAKE_BLOCK=1"
  else
    echo "Target ${TARGET} is not a block device." >&2
    exit 1
  fi
fi

canonicalize_source() {
  local source="$1" result=""
  if [[ -z "${source}" ]]; then
    echo ""
    return
  fi
  case "${source}" in
    /dev/*)
      if command -v realpath >/dev/null 2>&1; then
        result=$(realpath "${source}" 2>/dev/null || true)
      fi
      if [[ -z "${result}" ]]; then
        result="${source}"
      fi
      ;;
    PARTUUID=*)
      result=$(blkid -o device -t "${source}" 2>/dev/null || true)
      ;;
    UUID=*)
      result=$(blkid -U "${source#UUID=}" 2>/dev/null || true)
      ;;
    LABEL=*)
      result=$(blkid -L "${source#LABEL=}" 2>/dev/null || true)
      ;;
    *)
      if [[ -e "${source}" ]]; then
        result=$(realpath "${source}" 2>/dev/null || true)
      fi
      ;;
  esac
  echo "${result}"
}

ROOT_SOURCE=$(findmnt -no SOURCE / 2>/dev/null || true)
ROOT_DEVICE=$(canonicalize_source "${ROOT_SOURCE}")
if [[ -n "${ROOT_DEVICE}" ]]; then
  if [[ "${ROOT_DEVICE}" == "${TARGET}" ]]; then
    echo "Refusing to operate on the active root device (${TARGET})." >&2
    exit 1
  fi
  if [[ -b "${ROOT_DEVICE}" ]]; then
    root_base=$(basename "${ROOT_DEVICE}")
    target_base=$(basename "${TARGET}")
    if [[ "${root_base}" == "${target_base}" ]]; then
      echo "Refusing to operate on device that matches active root (${TARGET})." >&2
      exit 1
    fi
  fi
fi

ensure_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return
  fi
  local installer="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"
  log "Installing rpi-clone from geerlingguy/rpi-clone"
  if ! curl -fsSL "${installer}" | bash; then
    echo "Failed to install rpi-clone" >&2
    exit 1
  fi
}

ensure_rpi_clone

SOURCE_USED=$(df -B1 --output=used / | tail -n1)
TARGET_SIZE=$(lsblk -nb -o SIZE "${TARGET}" | head -n1)
if [[ -z "${SOURCE_USED}" || -z "${TARGET_SIZE}" ]]; then
  echo "Unable to determine disk sizes." >&2
  exit 1
fi
if (( TARGET_SIZE <= SOURCE_USED )); then
  echo "Target ${TARGET} is smaller than the used space on /." >&2
  exit 1
fi

log "Pre-flight cleanup for ${TARGET}"
sudo umount -R /mnt/clone 2>/dev/null || true
target_base=$(basename "${TARGET}")
if [[ "${target_base}" =~ [0-9]$ ]]; then
  part_glob=(/dev/"${target_base}"p*)
else
  part_glob=(/dev/"${target_base}"[0-9]*)
fi
for part in "${part_glob[@]}"; do
  [[ -e "${part}" ]] || continue
  sudo umount "${part}" 2>/dev/null || true
done
sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
sudo mkdir -p /mnt/clone/boot/firmware

if [[ "${WIPE}" == "1" ]]; then
  log "Wiping existing signatures from ${TARGET}"
  sudo wipefs -a "${TARGET}"
  if command -v udevadm >/dev/null 2>&1; then
    sudo udevadm settle
  fi
fi

run_rpi_clone() {
  local target="$1" clone_tmp retry_tmp fallback_output retry_output
  clone_tmp=$(mktemp)
  retry_tmp=$(mktemp)
  cleanup_tmp() {
    rm -f "${clone_tmp}" "${retry_tmp}"
  }
  trap cleanup_tmp RETURN

  log "Running rpi-clone -f -u ${target}"
  if rpi-clone -f -u "${target}" >"${clone_tmp}" 2>&1; then
    cat "${clone_tmp}"
    return 0
  fi

  fallback_output=$(<"${clone_tmp}")
  printf '%s\n' "${fallback_output}" >&2
  if [[ "${fallback_output}" == *"Unattended -u option not allowed when initializing"* ]]; then
    log "rpi-clone reported unattended restriction; retrying with -U"
    if rpi-clone -f -U "${target}" >"${retry_tmp}" 2>&1; then
      cat "${retry_tmp}"
      return 0
    fi
    retry_output=$(<"${retry_tmp}")
    printf '%s\n' "${retry_output}" >&2
    echo "rpi-clone failed even after -U fallback" >&2
    return 1
  fi

  echo "rpi-clone failed" >&2
  return 1
}

if ! run_rpi_clone "${TARGET}"; then
  exit 1
fi

log "Refreshing kernel partition table view for ${TARGET}"
sudo partprobe "${TARGET}" || true
if command -v udevadm >/dev/null 2>&1; then
  sudo udevadm settle
fi
sleep 1

CLONE_MOUNT="${CLONE_MOUNT:-/mnt/clone}"
BOOT_MOUNT="${CLONE_MOUNT}/boot/firmware"

sudo mkdir -p "${BOOT_MOUNT}"

retry_mount() {
  local dev="$1" mp="$2" tries="${3:-3}" delay="${4:-2}"
  local attempt
  for attempt in $(seq 1 "${tries}"); do
    if sudo mount "${dev}" "${mp}" 2>/dev/null; then
      log "Mounted ${dev} at ${mp} (attempt ${attempt}/${tries})"
      return 0
    fi
    log "Mount attempt ${attempt}/${tries} for ${dev} at ${mp} failed; retrying"
    sleep "${delay}"
    if command -v udevadm >/dev/null 2>&1; then
      sudo udevadm settle
    fi
  done
  return 1
}

mapfile -t TARGET_PARTS < <(lsblk -nr -o PATH "${TARGET}" 2>/dev/null || true)
BOOT_PART=""
ROOT_PART=""
for path in "${TARGET_PARTS[@]}"; do
  [[ "${path}" == "${TARGET}" ]] && continue
  if [[ -z "${BOOT_PART}" ]]; then
    BOOT_PART="${path}"
    continue
  fi
  if [[ -z "${ROOT_PART}" ]]; then
    ROOT_PART="${path}"
    continue
  fi
done

if [[ -z "${ROOT_PART}" || -z "${BOOT_PART}" ]]; then
  echo "Unable to determine target partitions for ${TARGET}." >&2
  exit 1
fi

if ! retry_mount "${ROOT_PART}" "${CLONE_MOUNT}" 5 3; then
  echo "Failed to mount clone root partition (${ROOT_PART}) at ${CLONE_MOUNT}." >&2
  exit 1
fi

if ! retry_mount "${BOOT_PART}" "${BOOT_MOUNT}" 5 3; then
  log "Boot partition mount failed; attempting recovery"
  sudo fsck.vfat -a "${BOOT_PART}" || true
  if command -v udevadm >/dev/null 2>&1; then
    sudo udevadm settle
  fi
  if ! retry_mount "${BOOT_PART}" "${BOOT_MOUNT}" 3 3; then
    log "Recreating boot filesystem on ${BOOT_PART}"
    sudo mkfs.vfat -F 32 -n bootfs "${BOOT_PART}"
    if command -v udevadm >/dev/null 2>&1; then
      sudo udevadm settle
    fi
    if ! retry_mount "${BOOT_PART}" "${BOOT_MOUNT}" 3 3; then
      echo "Failed to mount boot partition (${BOOT_PART}) after recovery." >&2
      exit 1
    fi
    log "Resyncing /boot/firmware to recovered boot partition"
    sudo rsync -aHAX /boot/firmware/ "${BOOT_MOUNT}/"
  fi
fi

resolve_mount_device() {
  local mount_point="$1" src
  src=$(findmnt -no SOURCE "${mount_point}" 2>/dev/null || true)
  canonicalize_source "${src}"
}

CLONE_ROOT_DEV=$(resolve_mount_device "${CLONE_MOUNT}")
CLONE_BOOT_DEV=$(resolve_mount_device "${BOOT_MOUNT}")
if [[ -z "${CLONE_ROOT_DEV}" || -z "${CLONE_BOOT_DEV}" ]]; then
  echo "Unable to resolve cloned partition devices." >&2
  exit 1
fi

ROOT_UUID=$(blkid -s UUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
ROOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)
BOOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)

CMDLINE_PATH="${BOOT_MOUNT}/cmdline.txt"
FSTAB_PATH="${CLONE_MOUNT}/etc/fstab"
if [[ ! -f "${CMDLINE_PATH}" || ! -f "${FSTAB_PATH}" ]]; then
  echo "Clone missing expected boot files (cmdline.txt or /etc/fstab)." >&2
  exit 1
fi

ROOT_IDENTIFIER=""
if [[ -n "${ROOT_PARTUUID}" ]]; then
  ROOT_IDENTIFIER="PARTUUID=${ROOT_PARTUUID}"
elif [[ -n "${ROOT_UUID}" ]]; then
  ROOT_IDENTIFIER="UUID=${ROOT_UUID}"
fi

if [[ -z "${ROOT_IDENTIFIER}" ]]; then
  echo "Unable to derive root identifier for cmdline.txt" >&2
  exit 1
fi

python3 - "${CMDLINE_PATH}" "${ROOT_IDENTIFIER}" <<'PY'
import sys
cmdline_path, new_root = sys.argv[1:3]
with open(cmdline_path, "r", encoding="utf-8") as fh:
    data = fh.read().strip()
parts = data.split()
for i, part in enumerate(parts):
    if part.startswith("root="):
        parts[i] = f"root={new_root}"
        break
else:
    parts.append(f"root={new_root}")
with open(cmdline_path, "w", encoding="utf-8") as fh:
    fh.write(" ".join(parts) + "\n")
PY

BOOT_MOUNTPOINT="/boot/firmware"
python3 - "${FSTAB_PATH}" \
  "${ROOT_UUID}" \
  "${ROOT_PARTUUID}" \
  "${BOOT_UUID}" \
  "${BOOT_PARTUUID}" \
  "${BOOT_MOUNTPOINT}" <<'PY'
import sys
path, root_uuid, root_partuuid, boot_uuid, boot_partuuid, boot_mount = sys.argv[1:7]
with open(path, "r", encoding="utf-8") as fh:
    lines = fh.readlines()

root_repl = None
boot_repl = None
if root_partuuid:
    root_repl = f"PARTUUID={root_partuuid}"
elif root_uuid:
    root_repl = f"UUID={root_uuid}"
if boot_uuid:
    boot_repl = f"UUID={boot_uuid}"
elif boot_partuuid:
    boot_repl = f"PARTUUID={boot_partuuid}"

updated = []
for line in lines:
    parts = line.split()
    if len(parts) < 2:
        updated.append(line)
        continue
    mount = parts[1]
    if mount == "/" and root_repl:
        parts[0] = root_repl
        updated.append("\t".join(parts) + "\n")
    elif mount == boot_mount and boot_repl:
        parts[0] = boot_repl
        updated.append("\t".join(parts) + "\n")
    else:
        updated.append(line)
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(updated)
PY

CLONED_BYTES=$(df -B1 --output=used "${CLONE_MOUNT}" | tail -n1)
CLONED_BYTES=${CLONED_BYTES:-0}

sync

log "Cleaning up mounts"
sudo umount "${BOOT_MOUNT}" || true
sudo umount "${CLONE_MOUNT}" || true
if ! rmdir "${CLONE_MOUNT}" 2>/dev/null; then
  log "Clone mount directory not empty; leaving in place"
fi

log "Clone complete summary:"
log "  target=${TARGET}"
log "  root=${ROOT_UUID:-${ROOT_PARTUUID:-unknown}}"
log "  boot=${BOOT_UUID:-${BOOT_PARTUUID:-unknown}}"
log "  bytes=${CLONED_BYTES}"
