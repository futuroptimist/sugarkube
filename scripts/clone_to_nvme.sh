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
  printf '[clone] %s\n' "$*"
}

warn() {
  printf '[clone][warn] %s\n' "$*" >&2
}

fatal() {
  printf '[clone][error] %s\n' "$*" >&2
  exit 1
}

ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"
if [[ "${ALLOW_NON_ROOT}" != "1" && ${EUID} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo --preserve-env=TARGET,WIPE "$0" "$@"
  else
    fatal "This script requires root privileges."
  fi
fi

if [[ ${EUID} -eq 0 ]]; then
  SUDO_CMD=""
else
  SUDO_CMD="sudo"
fi

run_sudo() {
  if [[ -n "${SUDO_CMD}" ]]; then
    sudo "$@"
  else
    "$@"
  fi
}

TARGET_ENV_DEFAULT="/dev/nvme0n1"
TARGET_OVERRIDE=""
TARGET="${TARGET:-${TARGET_ENV_DEFAULT}}"
WIPE="${WIPE:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET_OVERRIDE="$2"
      shift 2
      ;;
    --wipe)
      WIPE=1
      shift
      ;;
    --help|-h)
      cat <<'USAGE'
Usage: clone_to_nvme.sh [--target /dev/nvme0n1] [--wipe]
  --target  Explicit target disk (defaults to /dev/nvme0n1)
  --wipe    Wipe filesystem signatures on target before cloning
USAGE
      exit 0
      ;;
    *)
      fatal "Unknown argument: $1"
      ;;
  esac
done

resolve_device_path() {
  local source="$1"
  if [[ -z "${source}" ]]; then
    echo ""
    return
  fi
  if [[ "${source}" =~ ^/dev/ ]]; then
    echo "${source}"
  else
    echo "/dev/${source}"
  fi
}

resolve_mount_source() {
  local mount_src="$1" resolved=""
  if [[ -z "${mount_src}" ]]; then
    echo ""
    return
  fi
  case "${mount_src}" in
    /dev/*)
      resolved="${mount_src}"
      ;;
    UUID=*)
      resolved=$(blkid -U "${mount_src#UUID=}" 2>/dev/null || true)
      ;;
    PARTUUID=*)
      resolved=$(blkid -o device -t "PARTUUID=${mount_src#PARTUUID=}" 2>/dev/null || true)
      ;;
    LABEL=*)
      resolved=$(blkid -L "${mount_src#LABEL=}" 2>/dev/null || true)
      ;;
  esac
  echo "${resolved}"
}

if [[ -n "${TARGET_OVERRIDE}" ]]; then
  TARGET="${TARGET_OVERRIDE}"
fi

TARGET=$(resolve_device_path "${TARGET}")
if [[ -z "${TARGET}" ]]; then
  fatal "Unable to resolve target device."
fi

if [[ ! -b "${TARGET}" ]]; then
  if [[ "${ALLOW_FAKE_BLOCK:-0}" == "1" ]]; then
    warn "Target ${TARGET} is not a block device, continuing due to ALLOW_FAKE_BLOCK=1"
  else
    fatal "Target ${TARGET} is not a block device."
  fi
fi

TARGET=$(readlink -f "${TARGET}" 2>/dev/null || echo "${TARGET}")

TARGET_BASENAME=${TARGET#/dev/}
if [[ "${TARGET_BASENAME}" == mmcblk0* ]]; then
  fatal "Refusing to operate on the boot SD card (${TARGET})."
fi

derive_partition_path() {
  local disk_path="$1" part_index="$2" candidate="" resolved=""
  if [[ -z "${disk_path}" || -z "${part_index}" ]]; then
    echo ""
    return 1
  fi

  if command -v lsblk >/dev/null 2>&1; then
    while read -r path type partn; do
      if [[ "${type}" == "part" && "${partn}" == "${part_index}" ]]; then
        candidate="${path}"
        break
      fi
    done < <(lsblk -nr -o PATH,TYPE,PARTN "${disk_path}" 2>/dev/null || true)

    if [[ -n "${candidate}" ]]; then
      resolved=$(readlink -f "${candidate}" 2>/dev/null || echo "${candidate}")
      echo "${resolved}"
      return 0
    fi
  fi

  if [[ "${disk_path}" =~ [0-9]$ ]]; then
    candidate="${disk_path}p${part_index}"
  else
    candidate="${disk_path}${part_index}"
  fi

  if [[ -b "${candidate}" ]]; then
    resolved=$(readlink -f "${candidate}" 2>/dev/null || echo "${candidate}")
    echo "${resolved}"
    return 0
  fi

  echo ""
  return 1
}

current_root_src=$(findmnt -n -o SOURCE / 2>/dev/null || true)
current_root_dev=$(resolve_mount_source "${current_root_src}")
if [[ -n "${current_root_dev}" ]]; then
  root_disk_name=$(lsblk -no PKNAME "${current_root_dev}" 2>/dev/null || true)
  if [[ -n "${root_disk_name}" ]]; then
    current_root_disk="/dev/${root_disk_name}"
    if [[ "${current_root_disk}" == "${TARGET}" ]]; then
      fatal "Target ${TARGET} matches the active root disk."
    fi
  elif [[ "${current_root_dev}" == "${TARGET}"* ]]; then
    fatal "Target ${TARGET} matches the active root disk."
  fi
fi

strip_ansi() {
  sed -E $'s/\x1B\[[0-9;]*[[:alpha:]]//g'
}

ensure_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return
  fi
  local installer="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"
  log "Installing rpi-clone from geerlingguy/rpi-clone"
  if ! curl -fsSL "${installer}" | bash; then
    fatal "Failed to install rpi-clone"
  fi
}

ensure_rpi_clone

SOURCE_USED=$(df -B1 --output=used / | tail -n1)
TARGET_SIZE=$(lsblk -nb -o SIZE "${TARGET}" | head -n1)
if [[ -z "${SOURCE_USED}" || -z "${TARGET_SIZE}" ]]; then
  fatal "Unable to determine disk sizes."
fi
if (( TARGET_SIZE <= SOURCE_USED )); then
  fatal "Target ${TARGET} is smaller than the used space on /."
fi

CLONE_MOUNT="${CLONE_MOUNT:-/mnt/clone}"
BOOT_MOUNT="${CLONE_MOUNT}/boot/firmware"
BOOT_MOUNTPOINT="/boot/firmware"
BOOT_ALT_MOUNT="/boot"

discover_target_partitions() {
  local disk_path="$1" root_ref="$2" boot_ref="$3"
  local boot_part="" root_part=""
  local -a lsblk_parts=()

  if [[ -n "${disk_path}" ]]; then
    if mapfile -t lsblk_parts < <(lsblk -nr -o PATH,PARTN "${disk_path}" 2>/dev/null); then
      local part_line part_path part_num
      for part_line in "${lsblk_parts[@]}"; do
        read -r part_path part_num <<<"${part_line}"
        if [[ -z "${part_num}" ]]; then
          continue
        fi
        case "${part_num}" in
          1)
            boot_part="${part_path}"
            ;;
          2)
            root_part="${part_path}"
            ;;
        esac
      done
    fi
  fi

  if [[ -z "${boot_part}" ]]; then
    boot_part=$(derive_partition_path "${disk_path}" 1)
  fi
  if [[ -z "${root_part}" ]]; then
    root_part=$(derive_partition_path "${disk_path}" 2)
  fi

  printf -v "${root_ref}" '%s' "${root_part}"
  printf -v "${boot_ref}" '%s' "${boot_part}"
}

ROOT_PARTITION=""
BOOT_PARTITION=""
discover_target_partitions "${TARGET}" ROOT_PARTITION BOOT_PARTITION

if [[ -z "${ROOT_PARTITION}" || -z "${BOOT_PARTITION}" ]]; then
  fatal "Unable to derive partition paths for ${TARGET}"
fi

log "Pre-flight cleanup for ${TARGET}"
run_sudo umount -R "${CLONE_MOUNT}" 2>/dev/null || true
if mapfile -t TARGET_PARTITIONS < <(lsblk -nr -o PATH "${TARGET}" 2>/dev/null | tail -n +2); then
  for p in "${TARGET_PARTITIONS[@]}"; do
    run_sudo umount "${p}" 2>/dev/null || true
  done
fi
run_sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
run_sudo mkdir -p "${BOOT_MOUNT}"

if [[ "${WIPE}" == "1" ]]; then
  log "Wiping existing signatures from ${TARGET}"
  run_sudo wipefs --all --force "${TARGET}"
fi

maybe_udev_settle() {
  if command -v udevadm >/dev/null 2>&1; then
    run_sudo udevadm settle || true
  fi
  return 0
}

post_partition_sync() {
  if command -v partprobe >/dev/null 2>&1; then
    run_sudo partprobe "${TARGET}" || true
  fi
  maybe_udev_settle || true
  sleep 1
  return 0
}

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
  printf '%s\n' "${fallback_output}"
  if printf '%s\n' "${fallback_output}" | strip_ansi | \
      grep -Eq 'Unattended:?[[:space:]]*-u option not allowed'; then
    log "rpi-clone reported unattended initialization restriction; retrying with -U"
    if rpi-clone -f -U "${target}" >"${retry_tmp}" 2>&1; then
      cat "${retry_tmp}"
      return 0
    fi
    retry_output=$(<"${retry_tmp}")
    printf '%s\n' "${retry_output}" >&2
    return 1
  fi

  warn "rpi-clone failed"
  return 1
}

if ! run_rpi_clone "${TARGET}"; then
  fatal "rpi-clone execution failed"
fi

post_partition_sync

ROOT_PARTITION=$(derive_partition_path "${TARGET}" 2)
BOOT_PARTITION=$(derive_partition_path "${TARGET}" 1)

if [[ -z "${ROOT_PARTITION}" || -z "${BOOT_PARTITION}" ]]; then
  fatal "Unable to derive partition paths for ${TARGET}"
fi

log "Detected partitions: root=${ROOT_PARTITION}, boot=${BOOT_PARTITION}"

retry_mount() {
  local dev="$1" mp="$2" tries="${3:-3}" delay="${4:-2}"
  local attempt
  for attempt in $(seq 1 "${tries}"); do
    if run_sudo mount "${dev}" "${mp}"; then
      log "Mounted ${dev} to ${mp} (attempt ${attempt})"
      return 0
    fi
    warn "Mount attempt ${attempt} failed for ${dev} -> ${mp}, retrying"
    sleep "${delay}"
    maybe_udev_settle || true
  done
  return 1
}

if ! retry_mount "${ROOT_PARTITION}" "${CLONE_MOUNT}" 5 3; then
  fatal "Unable to mount root partition ${ROOT_PARTITION} at ${CLONE_MOUNT}"
fi

boot_resynced=0
if ! retry_mount "${BOOT_PARTITION}" "${BOOT_MOUNT}" 5 3; then
  warn "Boot partition failed to mount; attempting recovery"
  log "Running fsck.vfat on ${BOOT_PARTITION}"
  run_sudo fsck.vfat -a "${BOOT_PARTITION}" || true
  maybe_udev_settle || true
  if ! retry_mount "${BOOT_PARTITION}" "${BOOT_MOUNT}" 3 3; then
    warn "mkfs.vfat required for ${BOOT_PARTITION}"
    log "Reformatting ${BOOT_PARTITION} as FAT32"
    run_sudo mkfs.vfat -F 32 -n bootfs "${BOOT_PARTITION}"
    maybe_udev_settle || true
    if ! retry_mount "${BOOT_PARTITION}" "${BOOT_MOUNT}" 5 3; then
      fatal "Unable to recover boot partition ${BOOT_PARTITION}"
    fi
    boot_resynced=1
  fi
fi

if (( boot_resynced == 1 )); then
  log "Repopulating /boot/firmware after recovery"
  run_sudo rsync -aHAX /boot/firmware/ "${BOOT_MOUNT}/"
fi

CLONE_ROOT_DEV="${ROOT_PARTITION}"
CLONE_BOOT_DEV="${BOOT_PARTITION}"

maybe_udev_settle || true

ROOT_UUID=$(blkid -s UUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
ROOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)
BOOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)

CMDLINE_PATH="${BOOT_MOUNT}/cmdline.txt"
FSTAB_PATH="${CLONE_MOUNT}/etc/fstab"
if [[ ! -f "${CMDLINE_PATH}" || ! -f "${FSTAB_PATH}" ]]; then
  fatal "Clone missing expected boot files (cmdline.txt or /etc/fstab)."
fi

ROOT_SPEC=""
if [[ -n "${ROOT_PARTUUID}" ]]; then
  ROOT_SPEC="PARTUUID=${ROOT_PARTUUID}"
elif [[ -n "${ROOT_UUID}" ]]; then
  ROOT_SPEC="UUID=${ROOT_UUID}"
fi

BOOT_SPEC=""
if [[ -n "${BOOT_UUID}" ]]; then
  BOOT_SPEC="UUID=${BOOT_UUID}"
elif [[ -n "${BOOT_PARTUUID}" ]]; then
  BOOT_SPEC="PARTUUID=${BOOT_PARTUUID}"
fi

if [[ -z "${ROOT_SPEC}" ]]; then
  fatal "Unable to derive root identifier for cmdline.txt"
fi

ROOT_IDENTIFIER="${ROOT_SPEC}"

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

python3 - "${FSTAB_PATH}" "${ROOT_SPEC}" "${BOOT_SPEC}" "${BOOT_MOUNTPOINT}" "${BOOT_ALT_MOUNT}" <<'PY'
import sys
path, root_spec, boot_spec, boot_mount_primary, boot_mount_alt = sys.argv[1:6]
with open(path, "r", encoding="utf-8") as fh:
    lines = fh.readlines()

boot_mounts = {boot_mount_primary, boot_mount_alt}
updated = []
for line in lines:
    parts = line.split()
    if len(parts) < 2:
        updated.append(line)
        continue
    mount = parts[1]
    if mount == "/" and root_spec:
        parts[0] = root_spec
        updated.append("\t".join(parts) + "\n")
    elif mount in boot_mounts and boot_spec:
        parts[0] = boot_spec
        updated.append("\t".join(parts) + "\n")
    else:
        updated.append(line)
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(updated)
PY

CLONED_BYTES=$(df -B1 --output=used "${CLONE_MOUNT}" | tail -n1 2>/dev/null || echo 0)

log "Syncing cloned data to disk"
run_sudo sync
run_sudo umount "${BOOT_MOUNT}" || true
run_sudo umount "${CLONE_MOUNT}" || true

if [[ -d "${CLONE_MOUNT}" ]]; then
  rmdir "${CLONE_MOUNT}" 2>/dev/null || true
fi

log "Clone complete: target=${TARGET}, root=${ROOT_UUID:-${ROOT_PARTUUID}}, boot=${BOOT_UUID:-${BOOT_PARTUUID}}, bytes=${CLONED_BYTES}"
