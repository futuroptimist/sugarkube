#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

log() {
  printf '[preflight] %s\n' "$*"
}

fail() {
  local message="$1"
  local hint="${2:-}"
  printf '[preflight] ERROR: %s\n' "${message}" >&2
  if [ -n "${hint}" ]; then
    printf '[preflight] Hint: %s\n' "${hint}" >&2
  fi
  exit 1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command '$1' is missing from PATH."
  fi
}

resolve_device() {
  local source="$1"
  if [[ -z "${source}" ]]; then
    return 1
  fi
  case "${source}" in
    /dev/*)
      printf '%s\n' "${source}"
      ;;
    PARTUUID=*)
      blkid -o device -t "${source}" || return 1
      ;;
    UUID=*)
      blkid -U "${source#UUID=}" || return 1
      ;;
    LABEL=*)
      blkid -L "${source#LABEL=}" || return 1
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_disk_type() {
  local device="$1"
  local type
  type=$(lsblk -no TYPE "${device}" 2>/dev/null || true)
  if [[ "${type}" != "disk" ]]; then
    fail "${device} is not a disk (detected TYPE='${type}')." "Pass the whole disk (e.g. /dev/nvme0n1) as TARGET."
  fi
}

collect_mounts() {
  local device="$1"
  lsblk -J -o PATH,MOUNTPOINT "${device}" 2>/dev/null |
    python3 - <<'PY'
import json
import sys

def walk(node):
    if isinstance(node, dict):
        if 'path' in node:
            yield node
        for child in node.get('children', []):
            yield from walk(child)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)

try:
    payload = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)
for entry in walk(payload):
    mount = entry.get('mountpoint')
    if mount:
        print(f"{entry['path']}::{mount}")
PY
}

require_command findmnt
require_command lsblk
require_command blkid
require_command python3
require_command wipefs

TARGET=${TARGET:-${CLONE_TARGET:-}}
if [[ -z "${TARGET}" ]]; then
  fail "TARGET is not set." "Invoke with TARGET=/dev/nvme0n1 just preflight."
fi

TARGET=$(readlink -f "${TARGET}" 2>/dev/null || printf '%s\n' "${TARGET}")
if [[ ! -b "${TARGET}" ]]; then
  fail "${TARGET} is not a block device." "Confirm the device path with just show-disks."
fi

ensure_disk_type "${TARGET}"

declare -a checklist=()

default_summary() {
  local label="$1"
  checklist+=("[✔] ${label}")
}

boot_source=$(findmnt -no SOURCE / 2>/dev/null || true)
if [[ -z "${boot_source}" ]]; then
  fail "Unable to determine the boot device for /." "Verify that findmnt is available and rerun."
fi

boot_partition=$(resolve_device "${boot_source}" || true)
if [[ -z "${boot_partition}" ]]; then
  fail "Could not resolve boot source '${boot_source}'." "Use findmnt -no SOURCE / to inspect the current root mount."
fi

boot_disk_name=$(lsblk -no PKNAME "${boot_partition}" 2>/dev/null || true)
if [[ -n "${boot_disk_name}" ]]; then
  boot_disk="/dev/${boot_disk_name}"
else
  boot_disk="${boot_partition}"
fi

TARGET_DISK_NAME=$(lsblk -no PKNAME "${TARGET}" 2>/dev/null || true)
if [[ -n "${TARGET_DISK_NAME}" ]]; then
  target_disk="/dev/${TARGET_DISK_NAME}"
else
  target_disk="${TARGET}"
fi

target_real=$(readlink -f "${target_disk}" 2>/dev/null || printf '%s\n' "${target_disk}")
boot_disk_real=$(readlink -f "${boot_disk}" 2>/dev/null || printf '%s\n' "${boot_disk}")
boot_partition_real=$(readlink -f "${boot_partition}" 2>/dev/null || printf '%s\n' "${boot_partition}")

if [[ "${target_real}" == "${boot_disk_real}" ]]; then
  fail "TARGET ${TARGET} resolves to the active boot disk (${boot_disk_real})." "Choose an attached NVMe/USB disk that is not hosting /."
fi

if [[ "${target_real}" == "${boot_partition_real}" ]]; then
  fail "TARGET ${TARGET} points at the live root partition (${boot_partition_real})." "Pass the parent disk instead (e.g. /dev/mmcblk0 → /dev/mmcblk0p2)."
fi

default_summary "Boot disk ${boot_disk_real} will not be touched."

mapfile -t mounted_parts < <(collect_mounts "${TARGET}" || true)
if (( ${#mounted_parts[@]} > 0 )); then
  printf '[preflight] Mounted partitions detected on %s:%s' "${TARGET}" "\n" >&2
  for entry in "${mounted_parts[@]}"; do
    printf '  %s\n' "${entry}" >&2
  done
  fail "Target partitions are mounted." "Run just clean-mounts-hard first."
fi

default_summary "No target partitions are currently mounted."

signatures=$(wipefs -n --noheadings "${TARGET}" 2>/dev/null || true)
if [[ -n "${signatures}" && "${WIPE:-0}" != "1" ]]; then
  printf '[preflight] Existing signatures on %s:%s' "${TARGET}" "\n" >&2
  printf '%s\n' "${signatures}" >&2
  fail "Found existing filesystem/partition signatures on ${TARGET}." "Re-run with WIPE=1 TARGET=${TARGET} just preflight."
fi

if [[ "${WIPE:-0}" == "1" ]]; then
  if [[ "${WIPE_CONFIRM:-0}" != "1" ]]; then
    fail "WIPE=1 requested without WIPE_CONFIRM=1." "The just task sets WIPE_CONFIRM automatically; export it if running manually."
  fi
  if [[ -n "${signatures}" ]]; then
    log "Clearing existing signatures from ${TARGET}"
  else
    log "WIPE=1 set; ensuring ${TARGET} is blank before cloning"
  fi
  wipefs -a "${TARGET}"
  default_summary "wipefs -a executed for a clean starting point."
else
  default_summary "Existing signatures are acceptable (WIPE=0)."
fi

size=$(lsblk -dn -o SIZE "${TARGET}" 2>/dev/null || printf 'unknown')
model=$(lsblk -dn -o MODEL "${TARGET}" 2>/dev/null | sed -e 's/^ *//' -e 's/ *$//')
model=${model:-unknown}

root_usage=$(df -h --output=used / | tail -n1 | sed -e 's/^ *//' -e 's/ *$//')
mount_base_hint=${MOUNT_BASE:-/mnt/clone}

log "Target: ${TARGET} (size=${size}, model=${model})"
log "Boot root: ${boot_partition_real} (disk ${boot_disk_real})"
log "Root filesystem currently uses: ${root_usage}"

log "Checklist:"
for item in "${checklist[@]}"; do
  log "  ${item}"
  done

log "Next steps:"
log "  1. sudo TARGET=${TARGET} WIPE=${WIPE:-0} just clone-ssd"
log "  2. sudo TARGET=${TARGET} MOUNT_BASE=${mount_base_hint} just verify-clone"
log "  3. sudo just finalize-nvme"
log "Use just show-disks to double-check identifiers before cloning."

exit 0
