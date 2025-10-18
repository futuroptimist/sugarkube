#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[verify-clone] %s\n' "$*"
}

record_pass() {
  success_checks+=("$1")
}

record_fail() {
  error_checks+=("$1")
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[verify-clone] ERROR: Required command "%s" not found.\n' "$1" >&2
    exit 1
  fi
}

partition_path() {
  local disk="$1"
  local index="$2"
  if [[ "${disk}" =~ [0-9]$ ]]; then
    printf '%sp%s\n' "${disk}" "${index}"
  else
    printf '%s%s\n' "${disk}" "${index}"
  fi
}

cleanup() {
  local exit_code=$1
  set +e
  if [[ -n "${boot_mount:-}" ]] && mountpoint -q "${boot_mount}" 2>/dev/null; then
    umount "${boot_mount}" 2>/dev/null || umount -l "${boot_mount}" 2>/dev/null || true
  fi
  if [[ -n "${root_mount:-}" ]] && mountpoint -q "${root_mount}" 2>/dev/null; then
    umount "${root_mount}" 2>/dev/null || umount -l "${root_mount}" 2>/dev/null || true
  fi
  if [[ -n "${boot_mount:-}" ]] && [ -d "${boot_mount}" ]; then
    rmdir "${boot_mount}" 2>/dev/null || true
  fi
  if [[ -n "${root_mount:-}" ]] && [ -d "${root_mount}" ]; then
    find "${root_mount}" -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null || true
    rmdir "${root_mount}" 2>/dev/null || true
  fi
  trap - EXIT
  exit "${exit_code}"
}

trap 'cleanup "$?"' EXIT

require_command mount
require_command umount
require_command lsblk
require_command blkid
require_command python3
require_command fatlabel
require_command e2label

declare -a success_checks=()
declare -a error_checks=()

TARGET=${TARGET:-${CLONE_TARGET:-}}
if [[ -z "${TARGET}" ]]; then
  printf '[verify-clone] ERROR: TARGET is not set.\n' >&2
  exit 1
fi

TARGET=$(readlink -f "${TARGET}" 2>/dev/null || printf '%s\n' "${TARGET}")
if [[ ! -b "${TARGET}" ]]; then
  printf '[verify-clone] ERROR: %s is not a block device.\n' "${TARGET}" >&2
  exit 1
fi

root_part=$(partition_path "${TARGET}" 2)
boot_part=$(partition_path "${TARGET}" 1)

if [[ ! -b "${root_part}" ]]; then
  printf '[verify-clone] ERROR: Root partition %s not found.\n' "${root_part}" >&2
  exit 1
fi
if [[ ! -b "${boot_part}" ]]; then
  printf '[verify-clone] ERROR: Boot partition %s not found.\n' "${boot_part}" >&2
  exit 1
fi

MOUNT_BASE=${MOUNT_BASE:-/mnt/clone}
mkdir -p "${MOUNT_BASE}"
root_mount="${MOUNT_BASE}"
boot_mount=""

if mountpoint -q "${root_mount}" 2>/dev/null; then
  printf '[verify-clone] ERROR: %s is already mounted; run just clean-mounts-hard first.\n' "${root_mount}" >&2
  exit 1
fi

if ! mount -o ro "${root_part}" "${root_mount}"; then
  printf '[verify-clone] ERROR: Failed to mount %s at %s.\n' "${root_part}" "${root_mount}" >&2
  exit 1
fi

firmware_dir="${root_mount}/boot/firmware"
if [[ -d "${firmware_dir}" ]]; then
  boot_mount="${firmware_dir}"
else
  boot_mount="${root_mount}/boot"
fi

if [[ ! -d "${boot_mount}" ]]; then
  printf '[verify-clone] ERROR: Expected boot mount directory %s missing.\n' "${boot_mount}" >&2
  exit 1
fi

if mountpoint -q "${boot_mount}" 2>/dev/null; then
  printf '[verify-clone] ERROR: %s is already mounted; run just clean-mounts-hard first.\n' "${boot_mount}" >&2
  exit 1
fi

if ! mount -o ro -t vfat "${boot_part}" "${boot_mount}"; then
  printf '[verify-clone] ERROR: Failed to mount %s at %s.\n' "${boot_part}" "${boot_mount}" >&2
  exit 1
fi

root_partuuid=$(blkid -s PARTUUID -o value "${root_part}" 2>/dev/null || true)
root_uuid=$(blkid -s UUID -o value "${root_part}" 2>/dev/null || true)
boot_partuuid=$(blkid -s PARTUUID -o value "${boot_part}" 2>/dev/null || true)
boot_uuid=$(blkid -s UUID -o value "${boot_part}" 2>/dev/null || true)

log "Target ${TARGET}: root=${root_part} (PARTUUID=${root_partuuid:-n/a}), boot=${boot_part} (PARTUUID=${boot_partuuid:-n/a})"

if [[ -n "${root_partuuid}" ]]; then
  record_pass "Detected root PARTUUID ${root_partuuid}."
else
  record_fail "Missing PARTUUID for ${root_part}."
fi

cmdline_path="${boot_mount}/cmdline.txt"
if [[ -f "${cmdline_path}" ]]; then
  cmdline=$(tr '\n' ' ' <"${cmdline_path}" | sed -e 's/  */ /g')
  if [[ -n "${root_partuuid}" && "${cmdline}" =~ root=PARTUUID=${root_partuuid} ]]; then
    record_pass "cmdline.txt root=PARTUUID=${root_partuuid}."
  else
    record_fail "cmdline.txt root entry does not match PARTUUID=${root_partuuid}."
  fi
else
  record_fail "${cmdline_path} missing."
fi

fstab_path="${root_mount}/etc/fstab"
boot_mount_rel="/boot"
if [[ "${boot_mount}" == "${root_mount}/boot/firmware" ]]; then
  boot_mount_rel="/boot/firmware"
fi

if [[ -f "${fstab_path}" ]]; then
  fstab_output=$(python3 - <<'PY'
import sys
from pathlib import Path

path, root_partuuid, root_uuid, boot_partuuid, boot_uuid, boot_mount = sys.argv[1:7]
root_ok = False
boot_ok = False
root_pref = f"PARTUUID={root_partuuid}" if root_partuuid else None
root_alt = f"UUID={root_uuid}" if root_uuid else None
boot_pref = f"UUID={boot_uuid}" if boot_uuid else None
boot_alt = f"PARTUUID={boot_partuuid}" if boot_partuuid else None
for raw in Path(path).read_text(encoding='utf-8').splitlines():
    stripped = raw.strip()
    if not stripped or stripped.startswith('#'):
        continue
    parts = stripped.split()
    if len(parts) < 2:
        continue
    mount = parts[1]
    device = parts[0]
    if mount == '/':
        if root_pref and device == root_pref:
            root_ok = True
        elif root_alt and device == root_alt:
            root_ok = True
    elif mount == boot_mount:
        if boot_pref and device == boot_pref:
            boot_ok = True
        elif boot_alt and device == boot_alt:
            boot_ok = True
print('PASS' if root_ok else 'FAIL')
print('PASS' if boot_ok else 'FAIL')
PY
    "${fstab_path}" "${root_partuuid}" "${root_uuid}" "${boot_partuuid}" "${boot_uuid}" "${boot_mount_rel}" 2>/dev/null)
  python_status=$?
  if [[ ${python_status} -ne 0 ]]; then
    record_fail "Failed to parse ${fstab_path}."
  else
    read -r root_status boot_status <<<"${fstab_output}" || true
    if [[ "${root_status}" == "PASS" && -n "${root_partuuid}" ]]; then
      record_pass "fstab root entry matches PARTUUID=${root_partuuid}."
    elif [[ "${root_status}" == "PASS" ]]; then
      record_pass "fstab root entry matches available identifier."
    else
      record_fail "fstab root entry missing or mismatched."
    fi
    if [[ "${boot_status}" == "PASS" ]]; then
      record_pass "fstab ${boot_mount_rel} entry matches target identifiers."
    else
      record_fail "fstab ${boot_mount_rel} entry missing or mismatched."
    fi
  fi
else
  record_fail "${fstab_path} missing."
fi

boot_label=$(fatlabel "${boot_part}" 2>/dev/null | tr -d '\n' | sed -e 's/ *$//')
root_label=$(e2label "${root_part}" 2>/dev/null | tr -d '\n')

if [[ -z "${boot_label}" ]]; then
  record_fail "Unable to read FAT label for ${boot_part}."
elif [[ "${boot_label}" != "${boot_label^^}" ]]; then
  record_fail "Boot label '${boot_label}' is not upper-case."
elif [[ "${boot_label}" != "BOOTFS" ]]; then
  record_fail "Boot label '${boot_label}' should be BOOTFS."
else
  record_pass "Boot label BOOTFS confirmed."
fi

if [[ -z "${root_label}" ]]; then
  record_fail "Unable to read ext4 label for ${root_part}."
elif [[ "${root_label}" != "rootfs" ]]; then
  record_fail "Root label '${root_label}' should be rootfs."
else
  record_pass "Root label rootfs confirmed."
fi

log "Validation report:"
for item in "${success_checks[@]}"; do
  log "  [PASS] ${item}"
  done
for item in "${error_checks[@]}"; do
  log "  [FAIL] ${item}"
  done

if (( ${#error_checks[@]} > 0 )); then
  log "Run just clean-mounts-hard to clear mounts and address the failures above."
  cleanup 1
fi

log "All checks passed."
cleanup 0
