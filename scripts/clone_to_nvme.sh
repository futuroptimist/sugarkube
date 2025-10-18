#!/usr/bin/env bash
# Purpose: Clone the active SD card to an attached NVMe/USB disk and fix Bookworm boot configs.
# Usage: sudo TARGET=/dev/nvme0n1 WIPE=1 ./scripts/clone_to_nvme.sh
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
LOG_FILE="${ARTIFACT_DIR}/clone-to-nvme.log"
mkdir -p "${ARTIFACT_DIR}"
exec > >(tee "${LOG_FILE}") 2>&1

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

TARGET="${TARGET:-/dev/nvme0n1}"
WIPE="${WIPE:-0}"
ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"

if [[ "${ALLOW_NON_ROOT}" != "1" && ${EUID} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo --preserve-env=TARGET,WIPE,ALLOW_NON_ROOT "$0" "$@"
  fi
  echo "This script requires root privileges." >&2
  exit 1
fi

if [[ $# -gt 0 ]]; then
  case "$1" in
    --help|-h)
      cat <<'USAGE'
Usage: clone_to_nvme.sh
  TARGET=/dev/nvme0n1 WIPE=1 ./scripts/clone_to_nvme.sh

Environment variables:
  TARGET  Block device to clone to (default: /dev/nvme0n1)
  WIPE    Set to 1 to wipe filesystem signatures prior to cloning (default: 0)
USAGE
      exit 0
      ;;
    *)
      echo "Unknown positional argument: $1" >&2
      exit 1
      ;;
  esac
fi

if [[ "${TARGET}" != /dev/* ]]; then
  TARGET="/dev/${TARGET}"
fi

if [[ -z "${TARGET}" ]]; then
  echo "TARGET device must be provided." >&2
  exit 1
fi

if [[ ! -e "${TARGET}" ]]; then
  echo "TARGET ${TARGET} does not exist." >&2
  exit 1
fi

IS_BLOCK=0
if [[ -b "${TARGET}" ]]; then
  IS_BLOCK=1
fi

if [[ "${IS_BLOCK}" -ne 1 ]]; then
  if [[ "${ALLOW_FAKE_BLOCK:-0}" == "1" ]]; then
    log "[warn] TARGET ${TARGET} is not a block device (ALLOW_FAKE_BLOCK=1)"
  else
    echo "TARGET ${TARGET} is not a block device." >&2
    exit 1
  fi
fi

target_base=$(basename "${TARGET}")
root_source=$(findmnt -rn -o SOURCE / || true)
root_base=""
if [[ -n "${root_source}" ]]; then
  if [[ "${root_source}" =~ ^/dev/ ]]; then
    root_parent=$(lsblk -no PKNAME "${root_source}" 2>/dev/null || true)
    if [[ -n "${root_parent}" ]]; then
      root_base="${root_parent}"
    else
      root_base=$(basename "${root_source}")
    fi
  fi
fi

if [[ "${target_base}" == "${root_base}" ]]; then
  echo "Refusing to operate on the current root device (${TARGET})." >&2
  exit 1
fi

SCRIPT_CLONE_MOUNT="${CLONE_MOUNT:-/mnt/clone}"
BOOT_MOUNT="${SCRIPT_CLONE_MOUNT}/boot/firmware"
shopt -s nullglob

log "==> Pre-flight cleanup"
sudo umount -R "${SCRIPT_CLONE_MOUNT}" 2>/dev/null || true
for part in /dev/"${target_base}"p* /dev/"${target_base}"[0-9]*; do
  [[ -e "${part}" ]] || continue
  sudo umount "${part}" 2>/dev/null || true
done
sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
sudo mkdir -p "${BOOT_MOUNT}"

if [[ "${WIPE}" == "1" ]]; then
  log "==> Wiping existing signatures from ${TARGET}"
  if [[ "${IS_BLOCK}" -eq 1 ]]; then
    sudo wipefs -a "${TARGET}"
  else
    log "[warn] Skipping wipe; ${TARGET} is not a block device"
  fi
fi

ensure_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return
  fi
  local installer="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"
  log "==> Installing rpi-clone"
  if ! curl -fsSL "${installer}" | sudo bash; then
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

run_rpi_clone() {
  local target="$1" clone_tmp retry_tmp fallback_output retry_output
  clone_tmp=$(mktemp)
  retry_tmp=$(mktemp)
  cleanup_tmp() {
    rm -f "${clone_tmp}" "${retry_tmp}"
  }
  trap cleanup_tmp RETURN

  log "==> Running rpi-clone -f -u ${target}"
  if rpi-clone -f -u "${target}" >"${clone_tmp}" 2>&1; then
    cat "${clone_tmp}"
    return 0
  fi

  fallback_output=$(<"${clone_tmp}")
  printf '%s\n' "${fallback_output}"
  if [[ "${fallback_output}" == *"Unattended -u option not allowed when initializing"* ]]; then
    log "==> Falling back to rpi-clone -f -U ${target}"
    if rpi-clone -f -U "${target}" >"${retry_tmp}" 2>&1; then
      cat "${retry_tmp}"
      return 0
    fi
    retry_output=$(<"${retry_tmp}")
    printf '%s\n' "${retry_output}" >&2
    echo "rpi-clone failed after -U fallback" >&2
    return 1
  fi

  echo "rpi-clone failed" >&2
  return 1
}

if ! run_rpi_clone "${TARGET}"; then
  exit 1
fi

if [[ "${IS_BLOCK}" -eq 1 ]]; then
  log "==> Refreshing partition table"
  if command -v partprobe >/dev/null 2>&1; then
    sudo partprobe "${TARGET}" || true
  fi
  sudo udevadm settle
  sleep 1
fi

partition_list() {
  lsblk -nr -o PATH,TYPE "${TARGET}" | awk '$2 == "part" {print $1}'
}

mapfile -t TARGET_PARTS < <(partition_list)
if (( ${#TARGET_PARTS[@]} < 2 )); then
  log "Waiting for partitions on ${TARGET} to appear"
  for _ in {1..5}; do
    sleep 1
    sudo udevadm settle
    mapfile -t TARGET_PARTS < <(partition_list)
    if (( ${#TARGET_PARTS[@]} >= 2 )); then
      break
    fi
  done
fi

if (( ${#TARGET_PARTS[@]} < 2 )); then
  echo "Expected boot and root partitions on ${TARGET}" >&2
  exit 1
fi

BOOT_PART="${TARGET_PARTS[0]}"
ROOT_PART="${TARGET_PARTS[-1]}"

retry_mount() {
  local dev="$1" mount_point="$2" tries="${3:-3}" delay="${4:-2}"
  local attempt
  for attempt in $(seq 1 "${tries}"); do
    if sudo mount "${dev}" "${mount_point}"; then
      return 0
    fi
    if (( attempt < tries )); then
      log "Mount attempt ${attempt}/${tries} for ${dev} -> ${mount_point} failed; retrying in ${delay}s"
      sleep "${delay}"
      sudo udevadm settle
    fi
  done
  sudo udevadm settle
  return 1
}

log "==> Mounting cloned root ${ROOT_PART}"
sudo mkdir -p "${SCRIPT_CLONE_MOUNT}"
if ! retry_mount "${ROOT_PART}" "${SCRIPT_CLONE_MOUNT}" 5 3; then
  echo "Unable to mount cloned root filesystem (${ROOT_PART})" >&2
  exit 1
fi

log "==> Mounting cloned boot ${BOOT_PART}"
if ! retry_mount "${BOOT_PART}" "${BOOT_MOUNT}" 5 3; then
  log "Boot mount failed; attempting recovery"
  sudo fsck.vfat -a "${BOOT_PART}" || true
  sudo udevadm settle
  if ! retry_mount "${BOOT_PART}" "${BOOT_MOUNT}" 5 3; then
    log "Recreating boot filesystem on ${BOOT_PART}"
    sudo mkfs.vfat -F 32 -n bootfs "${BOOT_PART}"
    sudo udevadm settle
    sleep 1
    if ! retry_mount "${BOOT_PART}" "${BOOT_MOUNT}" 5 3; then
      echo "Unable to mount cloned boot partition (${BOOT_PART})" >&2
      exit 1
    fi
    log "Resyncing /boot/firmware contents"
    sudo rsync -aHAX /boot/firmware/ "${BOOT_MOUNT}/"
  fi
fi

resolve_mount_device() {
  local mount_point="$1" src
  src=$(findmnt -no SOURCE "${mount_point}" 2>/dev/null || true)
  if [[ -z "${src}" ]]; then
    return 1
  fi
  if [[ "${src}" =~ ^/dev/ ]]; then
    printf '%s\n' "${src}"
    return 0
  fi
  if [[ "${src}" =~ ^UUID= ]]; then
    blkid -U "${src#UUID=}"
    return 0
  fi
  if [[ "${src}" =~ ^PARTUUID= ]]; then
    blkid -o device -t "PARTUUID=${src#PARTUUID=}"
    return 0
  fi
  return 1
}

CLONE_ROOT_DEV=$(resolve_mount_device "${SCRIPT_CLONE_MOUNT}" || true)
CLONE_BOOT_DEV=$(resolve_mount_device "${BOOT_MOUNT}" || true)
if [[ -z "${CLONE_ROOT_DEV}" || -z "${CLONE_BOOT_DEV}" ]]; then
  echo "Unable to resolve cloned partition devices." >&2
  exit 1
fi

ROOT_UUID=$(blkid -s UUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
ROOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)
BOOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)

CMDLINE_PATH="${BOOT_MOUNT}/cmdline.txt"
FSTAB_PATH="${SCRIPT_CLONE_MOUNT}/etc/fstab"
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

python3 - "${FSTAB_PATH}" "${ROOT_UUID}" "${ROOT_PARTUUID}" "${BOOT_UUID}" "${BOOT_PARTUUID}" <<'PY'
import sys
path, root_uuid, root_partuuid, boot_uuid, boot_partuuid = sys.argv[1:6]
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
    elif mount in ("/boot", "/boot/firmware") and boot_repl:
        parts[0] = boot_repl
        updated.append("\t".join(parts) + "\n")
    else:
        updated.append(line)
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(updated)
PY

CLONED_BYTES=$(df -B1 --output=used "${SCRIPT_CLONE_MOUNT}" | tail -n1)
CLONED_BYTES=${CLONED_BYTES:-0}

sync

log "==> Cleaning up mounts"
sudo umount "${BOOT_MOUNT}" || true
sudo umount "${SCRIPT_CLONE_MOUNT}" || true
rmdir "${BOOT_MOUNT}" 2>/dev/null || true
rmdir "${SCRIPT_CLONE_MOUNT}" 2>/dev/null || true

log "✅ Clone complete: target=${TARGET}, root=${ROOT_UUID:-${ROOT_PARTUUID}}, boot=${BOOT_UUID:-${BOOT_PARTUUID}}, used_bytes=${CLONED_BYTES}"
