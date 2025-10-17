#!/usr/bin/env bash
# Purpose: Clone the active SD card to an attached NVMe/USB disk and fix Bookworm boot configs.
# Usage: sudo WIPE=1 ./scripts/clone_to_nvme.sh
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
ARTIFACT_DIR="${REPO_ROOT}/artifacts"
LOG_FILE="${ARTIFACT_DIR}/clone-to-nvme.log"

resolve_device() {
  local source="$1"
  if [[ -z "${source}" ]]; then
    echo "" && return
  fi
  if [[ "${source}" =~ ^/dev/ ]]; then
    echo "${source}"
  else
    echo "/dev/${source}"
  fi
}

run_rpi_clone_with_fallback() {
  local target_device="$1"
  local clone_tmp fallback_tmp status
  local -a base_args=(-f)
  local unattended_flag="-u"
  local unattended_init_flag="-U"
  clone_tmp=$(mktemp)
  fallback_tmp=""

  cleanup_clone_logs() {
    local clone_path="${clone_tmp:-}"
    local fallback_path="${fallback_tmp:-}"
    rm -f "${clone_path}" "${fallback_path}" 2>/dev/null || true
  }
  trap cleanup_clone_logs RETURN

  echo "Running rpi-clone unattended clone for ${target_device}"

  set +e
  rpi-clone "${base_args[@]}" "${unattended_flag}" "${target_device}" > >(tee "${clone_tmp}") 2>&1
  status=$?
  set -e

  if [[ ${status} -eq 0 ]]; then
    return 0
  fi

  if grep -Fq "Unattended -u option not allowed when initializing" "${clone_tmp}"; then
    echo "rpi-clone refused unattended init; retrying with manual -U"
    fallback_tmp=$(mktemp)
    trap cleanup_clone_logs RETURN
    set +e
    rpi-clone "${base_args[@]}" "${unattended_init_flag}" "${target_device}" > >(tee "${fallback_tmp}") 2>&1
    status=$?
    set -e
    if [[ ${status} -eq 0 ]]; then
      return 0
    fi
  fi

  echo "rpi-clone failed. Output:" >&2
  cat "${clone_tmp}" >&2 || true
  if [[ -n "${fallback_tmp}" ]]; then
    cat "${fallback_tmp}" >&2 || true
  fi
  return 1
}

ensure_clone_mounts() {
  local target_device="$1" clone_mount="$2"
  if mountpoint -q "${clone_mount}"; then
    return 0
  fi

  echo "Clone root not mounted at ${clone_mount}; attempting manual mount"
  mkdir -p "${clone_mount}" "${clone_mount}/boot/firmware"

  mapfile -t target_parts < <(
    lsblk -nr -o NAME,TYPE "${target_device}" |
      awk '$2=="part" {print $1}'
  )

  if (( ${#target_parts[@]} == 0 )); then
    echo "No partitions detected on ${target_device} after clone." >&2
    return 1
  fi

  local root_index=$(( ${#target_parts[@]} - 1 ))
  local root_part="${target_parts[${root_index}]}"
  local boot_part="${target_parts[0]}"

  if ! mount "/dev/${root_part}" "${clone_mount}"; then
    echo "Failed to mount cloned root /dev/${root_part} at ${clone_mount}" >&2
    return 1
  fi

  if ! mountpoint -q "${clone_mount}/boot/firmware"; then
    if [[ "${boot_part}" != "${root_part}" ]]; then
      if ! mount "/dev/${boot_part}" "${clone_mount}/boot/firmware"; then
        echo "Warning: unable to mount boot partition /dev/${boot_part}" >&2
      fi
    fi
  fi
}

resolve_mount_device() {
  local mount_point="$1"
  local src
  src=$(findmnt -no SOURCE "${mount_point}" 2>/dev/null || true)
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

ensure_rpi_clone() {
  if command -v rpi-clone >/dev/null 2>&1; then
    return
  fi
  local installer="https://raw.githubusercontent.com/geerlingguy/rpi-clone/master/install"
  echo "Installing rpi-clone from geerlingguy/rpi-clone"
  if ! curl -fsSL "${installer}" | bash; then
    echo "Failed to install rpi-clone" >&2
    exit 1
  fi
}

if [[ "${SKIP_CLONE_TO_NVME_MAIN:-0}" == "1" ]]; then
  if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
  fi
  exit 0
fi

mkdir -p "${ARTIFACT_DIR}"
exec > >(tee "${LOG_FILE}") 2>&1

if [[ ${EUID} -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo WIPE="${WIPE:-0}" TARGET="${TARGET:-}" "$0" "$@"
  fi
  echo "This script requires root privileges." >&2
  exit 1
fi

TARGET_OVERRIDE=""
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
  --target  Explicit target disk (defaults to first non-SD disk)
  --wipe    Wipe filesystem signatures on target before cloning
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

TARGET_DEVICE="${TARGET_OVERRIDE:-${TARGET:-}}"
DETECT_SCRIPT="${SCRIPT_DIR}/detect_target_disk.sh"

if [[ -z "${TARGET_DEVICE}" ]]; then
  if [[ ! -x "${DETECT_SCRIPT}" ]]; then
    echo "Device detection helper missing: ${DETECT_SCRIPT}" >&2
    exit 1
  fi
  TARGET_DEVICE=$("${DETECT_SCRIPT}")
fi

TARGET_DEVICE=$(resolve_device "${TARGET_DEVICE}")
if [[ -z "${TARGET_DEVICE}" ]]; then
  echo "Unable to resolve target device" >&2
  exit 1
fi

TARGET_BASENAME=${TARGET_DEVICE#/dev/}
if [[ "${TARGET_BASENAME}" == mmcblk0* ]]; then
  echo "Refusing to operate on the boot SD card (${TARGET_DEVICE})." >&2
  exit 1
fi

if [[ ! -b "${TARGET_DEVICE}" ]]; then
  echo "Target ${TARGET_DEVICE} is not a block device." >&2
  exit 1
fi

ensure_rpi_clone

SOURCE_USED=$(df -B1 --output=used / | tail -n1)
TARGET_SIZE=$(lsblk -nb -o SIZE "${TARGET_DEVICE}" | head -n1)
if [[ -z "${SOURCE_USED}" || -z "${TARGET_SIZE}" ]]; then
  echo "Unable to determine disk sizes." >&2
  exit 1
fi
if (( TARGET_SIZE <= SOURCE_USED )); then
  echo "Target ${TARGET_DEVICE} is smaller than the used space on /." >&2
  exit 1
fi

mapfile -t mounted_parts < <(
  lsblk -nr -o NAME,MOUNTPOINT "${TARGET_DEVICE}" |
    awk '$2!="" {print $1":"$2}'
)
if (( ${#mounted_parts[@]} > 0 )); then
  echo "Refusing to clone: target partitions are mounted:" >&2
  printf '  %s\n' "${mounted_parts[@]}" >&2
  exit 1
fi

if [[ "${WIPE}" == "1" ]]; then
  echo "Wiping existing signatures from ${TARGET_DEVICE}"
  wipefs --all --force "${TARGET_DEVICE}"
fi

if ! run_rpi_clone_with_fallback "${TARGET_DEVICE}"; then
  echo "rpi-clone failed" >&2
  exit 1
fi

CLONE_MOUNT="/mnt/clone"
if ! ensure_clone_mounts "${TARGET_DEVICE}" "${CLONE_MOUNT}"; then
  echo "Unable to mount cloned root at ${CLONE_MOUNT}" >&2
  exit 1
fi

if ! mountpoint -q "${CLONE_MOUNT}"; then
  echo "Clone root is not mounted at ${CLONE_MOUNT}" >&2
  exit 1
fi

CLONE_ROOT_DEV=$(resolve_mount_device "${CLONE_MOUNT}")
CLONE_BOOT_DEV=$(resolve_mount_device "${CLONE_MOUNT}/boot/firmware")
if [[ -z "${CLONE_ROOT_DEV}" || -z "${CLONE_BOOT_DEV}" ]]; then
  echo "Unable to resolve cloned partition devices." >&2
  exit 1
fi

ROOT_UUID=$(blkid -s UUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
ROOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_ROOT_DEV}" 2>/dev/null || true)
BOOT_UUID=$(blkid -s UUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)
BOOT_PARTUUID=$(blkid -s PARTUUID -o value "${CLONE_BOOT_DEV}" 2>/dev/null || true)

CMDLINE_PATH="${CLONE_MOUNT}/boot/firmware/cmdline.txt"
FSTAB_PATH="${CLONE_MOUNT}/etc/fstab"
if [[ ! -f "${CMDLINE_PATH}" || ! -f "${FSTAB_PATH}" ]]; then
  echo "Clone did not expose expected Bookworm paths." >&2
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

def choose(preferred, fallback):
    return preferred if preferred else fallback

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
    elif mount == "/boot/firmware" and boot_repl:
        parts[0] = boot_repl
        updated.append("\t".join(parts) + "\n")
    else:
        updated.append(line)
with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(updated)
PY

sync

CLONED_BYTES=$(df -B1 --output=used "${CLONE_MOUNT}" | tail -n1)
CLONED_BYTES=${CLONED_BYTES:-0}

ROOT_DISPLAY="${ROOT_UUID:-${ROOT_PARTUUID}}"
BOOT_DISPLAY="${BOOT_UUID:-${BOOT_PARTUUID}}"

printf '✅ Clone complete: target=%s, root=%s, boot=%s, bytes=%s\n' \
  "${TARGET_DEVICE}" "${ROOT_DISPLAY}" "${BOOT_DISPLAY}" "${CLONED_BYTES}"
