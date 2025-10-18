#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
LOG_FILE="${ARTIFACT_DIR}/clone-to-nvme.log"
mkdir -p "${ARTIFACT_DIR}"
exec > >(tee "${LOG_FILE}") 2>&1

log() {
  local level="$1" message="$2"
  printf '[%(%Y-%m-%dT%H:%M:%S%z)T] [%s] %s\n' -1 "${level}" "${message}"
}

ALLOW_NON_ROOT="${ALLOW_NON_ROOT:-0}"
if [[ "${ALLOW_NON_ROOT}" != "1" && ${EUID} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo --preserve-env=TARGET,WIPE,ALLOW_NON_ROOT "$0" "$@"
  fi
  echo "This script requires root privileges." >&2
  exit 1
fi

TARGET="${TARGET:-/dev/nvme0n1}"
WIPE="${WIPE:-0}"
DETECT_SCRIPT="${SCRIPT_DIR}/detect_target_disk.sh"

resolve_device() {
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

if [[ -z "${TARGET}" ]]; then
  if [[ -x "${DETECT_SCRIPT}" ]]; then
    TARGET=$("${DETECT_SCRIPT}")
  fi
fi

TARGET=$(resolve_device "${TARGET}")
if [[ -z "${TARGET}" ]]; then
  log ERROR "Unable to resolve target device"
  exit 1
fi

if [[ ! -b "${TARGET}" ]]; then
  if [[ "${ALLOW_FAKE_BLOCK:-0}" == "1" ]]; then
    log WARN "Target ${TARGET} is not a block device, continuing due to ALLOW_FAKE_BLOCK=1"
  else
    log ERROR "Target ${TARGET} is not a block device"
    exit 1
  fi
fi

TARGET_BASENAME=${TARGET#/dev/}
if [[ "${TARGET_BASENAME}" == mmcblk0* ]]; then
  log ERROR "Refusing to operate on the boot SD card (${TARGET})."
  exit 1
fi

active_root=$(findmnt -nr -o SOURCE / || true)
if [[ -n "${active_root}" ]]; then
  if [[ "${active_root}" =~ ^PARTUUID= ]]; then
    active_root=$(blkid -o device -t "${active_root}")
  elif [[ "${active_root}" =~ ^UUID= ]]; then
    active_root=$(blkid -U "${active_root#UUID=}")
  fi
fi
if [[ -n "${active_root}" ]]; then
  root_parent=$(lsblk -no PKNAME "${active_root}" 2>/dev/null || true)
  target_parent=$(lsblk -no PKNAME "${TARGET}" 2>/dev/null || true)
  if [[ -n "${root_parent}" && "${root_parent}" == "${TARGET_BASENAME}" ]]; then
    log ERROR "Target ${TARGET} appears to be the active root device. Aborting."
    exit 1
  fi
  if [[ -n "${root_parent}" && -n "${target_parent}" && "${root_parent}" == "${target_parent}" ]]; then
    log ERROR "Target ${TARGET} shares the same parent as the active root. Aborting."
    exit 1
  fi
fi

log INFO "Starting clone to ${TARGET} (WIPE=${WIPE})"

# Pre-flight cleanup
log INFO "Cleaning up stale mounts"
sudo umount -R /mnt/clone 2>/dev/null || true
for p in /dev/"${TARGET_BASENAME}"p*; do
  [[ -e "${p}" ]] || continue
  sudo umount "${p}" 2>/dev/null || true
done
sudo systemctl stop mnt-clone.mount mnt-clone.automount 2>/dev/null || true
sudo mkdir -p /mnt/clone/boot/firmware

ensure_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return
  fi
  local installer="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"
  log INFO "Installing rpi-clone from geerlingguy/rpi-clone"
  if ! curl -fsSL "${installer}" | bash; then
    log ERROR "Failed to install rpi-clone"
    exit 1
  fi
}

ensure_rpi_clone

SOURCE_USED=$(df -B1 --output=used / | tail -n1)
TARGET_SIZE=$(lsblk -nb -o SIZE "${TARGET}" | head -n1)
if [[ -z "${SOURCE_USED}" || -z "${TARGET_SIZE}" ]]; then
  log ERROR "Unable to determine disk sizes"
  exit 1
fi
if (( TARGET_SIZE <= SOURCE_USED )); then
  log ERROR "Target ${TARGET} is smaller than the used space on /."
  exit 1
fi

mapfile -t mounted_parts < <(lsblk -nr -o NAME,MOUNTPOINT "${TARGET}" | awk '$2!="" {print $1":"$2}')
if (( ${#mounted_parts[@]} > 0 )); then
  log ERROR "Refusing to clone: target partitions are mounted"
  printf '  %s\n' "${mounted_parts[@]}" >&2
  exit 1
fi

if [[ "${WIPE}" == "1" ]]; then
  log INFO "Wiping existing signatures from ${TARGET}"
  sudo wipefs -a "${TARGET}"
fi

refresh_partitions() {
  sudo partprobe "${TARGET}" || true
  if command -v udevadm >/dev/null 2>&1; then
    sudo udevadm settle
  fi
  sleep 1
}

run_rpi_clone() {
  local device="$1" output_tmp fallback_tmp
  output_tmp=$(mktemp)
  fallback_tmp=$(mktemp)
  cleanup_tmp() {
    rm -f "${output_tmp}" "${fallback_tmp}"
  }
  trap cleanup_tmp RETURN

  log INFO "Running rpi-clone -f -u ${device}"
  if rpi-clone -f -u "${device}" >"${output_tmp}" 2>&1; then
    cat "${output_tmp}"
    return 0
  fi

  if grep -q "Unattended -u option not allowed when initializing" "${output_tmp}"; then
    cat "${output_tmp}"
    log WARN "rpi-clone reported unattended restriction; retrying with -U"
    if rpi-clone -f -U "${device}" >"${fallback_tmp}" 2>&1; then
      cat "${fallback_tmp}"
      return 0
    fi
    cat "${fallback_tmp}" >&2
    log ERROR "rpi-clone failed even after -U fallback"
    return 1
  fi

  cat "${output_tmp}" >&2
  log ERROR "rpi-clone failed"
  return 1
}

if ! run_rpi_clone "${TARGET}"; then
  exit 1
fi

refresh_partitions

read_target_partitions() {
  mapfile -t TARGET_PARTITIONS < <(lsblk -nr -o PATH "${TARGET}" 2>/dev/null | awk -v target="${TARGET}" '$1!=target')
}

TARGET_PARTITIONS=()
read_target_partitions
BOOT_PART=${TARGET_PARTITIONS[0]:-${TARGET}p1}
ROOT_PART=${TARGET_PARTITIONS[-1]:-${TARGET}p2}

log INFO "Target partitions: boot=${BOOT_PART}, root=${ROOT_PART}"

retry_mount() {
  local dev="$1" mp="$2" tries="${3:-3}" delay="${4:-2}" attempt
  for ((attempt = 1; attempt <= tries; attempt++)); do
    if sudo mount "${dev}" "${mp}"; then
      return 0
    fi
    sleep "${delay}"
    if command -v udevadm >/dev/null 2>&1; then
      sudo udevadm settle
    fi
  done
  return 1
}

log INFO "Ensuring root partition is mounted"
if ! retry_mount "${ROOT_PART}" /mnt/clone 5 2; then
  log WARN "Root partition mount failed, running e2fsck"
  sudo e2fsck -f -y "${ROOT_PART}" || true
  if ! retry_mount "${ROOT_PART}" /mnt/clone 3 3; then
    log ERROR "Root partition mount failed after fsck"
    exit 1
  fi
fi

log INFO "Ensuring boot firmware partition is mounted"
boot_repaired=0
if ! retry_mount "${BOOT_PART}" /mnt/clone/boot/firmware 5 2; then
  log WARN "Boot partition mount failed, running fsck.vfat"
  sudo fsck.vfat -a "${BOOT_PART}" || true
  if command -v udevadm >/dev/null 2>&1; then
    sudo udevadm settle
  fi
  if ! retry_mount "${BOOT_PART}" /mnt/clone/boot/firmware 3 3; then
    log WARN "Boot partition mount still failing, reformatting"
    sudo mkfs.vfat -F 32 -n bootfs "${BOOT_PART}"
    if command -v udevadm >/dev/null 2>&1; then
      sudo udevadm settle
    fi
    boot_repaired=1
    if ! retry_mount "${BOOT_PART}" /mnt/clone/boot/firmware 3 3; then
      log ERROR "Boot partition mount failed after mkfs"
      exit 1
    fi
  else
    boot_repaired=1
  fi
fi

if (( boot_repaired == 1 )); then
  log INFO "Re-syncing /boot/firmware contents to repaired partition"
  sudo rsync -aHAX /boot/firmware/ /mnt/clone/boot/firmware/
fi

sudo findmnt /mnt/clone >/dev/null 2>&1 || { log ERROR "Root mount missing after verification"; exit 1; }
sudo findmnt /mnt/clone/boot/firmware >/dev/null 2>&1 || { log ERROR "Boot mount missing after verification"; exit 1; }

ROOT_UUID=$(sudo blkid -s UUID -o value "${ROOT_PART}" 2>/dev/null || true)
ROOT_PARTUUID=$(sudo blkid -s PARTUUID -o value "${ROOT_PART}" 2>/dev/null || true)
BOOT_UUID=$(sudo blkid -s UUID -o value "${BOOT_PART}" 2>/dev/null || true)
BOOT_PARTUUID=$(sudo blkid -s PARTUUID -o value "${BOOT_PART}" 2>/dev/null || true)

CMDLINE_PATH="/mnt/clone/boot/firmware/cmdline.txt"
FSTAB_PATH="/mnt/clone/etc/fstab"
if [[ ! -f "${CMDLINE_PATH}" || ! -f "${FSTAB_PATH}" ]]; then
  log ERROR "Clone missing expected boot files (cmdline.txt or /etc/fstab)"
  exit 1
fi

ROOT_IDENTIFIER=""
if [[ -n "${ROOT_PARTUUID}" ]]; then
  ROOT_IDENTIFIER="PARTUUID=${ROOT_PARTUUID}"
elif [[ -n "${ROOT_UUID}" ]]; then
  ROOT_IDENTIFIER="UUID=${ROOT_UUID}"
fi

if [[ -z "${ROOT_IDENTIFIER}" ]]; then
  log ERROR "Unable to derive root identifier for cmdline.txt"
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
path, root_uuid, root_partuuid, boot_uuid, boot_partuuid = sys.argv[1:5]
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
    elif mount in {"/boot/firmware", "/boot"} and boot_repl:
        parts[0] = boot_repl
        updated.append("\t".join(parts) + "\n")
    else:
        updated.append(line)
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(updated)
PY

CLONED_BYTES=$(df -B1 --output=used /mnt/clone 2>/dev/null | tail -n1 || echo "0")

sync

log INFO "Clone complete; beginning cleanup"

sudo umount /mnt/clone/boot/firmware || true
sudo umount /mnt/clone || true
if ! rmdir /mnt/clone 2>/dev/null; then
  log WARN "/mnt/clone not empty or in use; leaving directory in place"
fi

log INFO "✅ Clone complete: target=${TARGET}, root=${ROOT_UUID:-${ROOT_PARTUUID}}, boot=${BOOT_UUID:-${BOOT_PARTUUID}}, bytes=${CLONED_BYTES}"
