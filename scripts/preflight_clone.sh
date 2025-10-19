#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_NAME=$(basename "$0")
TARGET=${TARGET:-}
WIPE=${WIPE:-0}

cleanup() {
  # Keep EXIT traps from swallowing SIGINT if extended in the future.
  :
}
trap cleanup EXIT

log() {
  printf '[%s] %s\n' "${SCRIPT_NAME}" "$*"
}

die() {
  local message=$1
  local hint=${2:-""}
  if [ -n "$hint" ]; then
    printf '%s: %s (%s)\n' "${SCRIPT_NAME}" "$message" "$hint" >&2
  else
    printf '%s: %s\n' "${SCRIPT_NAME}" "$message" >&2
  fi
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing required command: $1" "install it and retry"
  fi
}

require_cmd findmnt
require_cmd lsblk
require_cmd blkid
require_cmd wipefs

if [ -z "$TARGET" ]; then
  die "TARGET is not set" "export TARGET=/dev/nvme0n1"
fi

if [ ! -b "$TARGET" ]; then
  die "Target $TARGET is not a block device" "double-check the device path"
fi

resolve_source() {
  local source=$1
  if [ -z "$source" ]; then
    return 1
  fi
  case "$source" in
    PARTUUID=*)
      blkid -t "PARTUUID=${source#PARTUUID=}" -o device 2>/dev/null | head -n1
      return
      ;;
    UUID=*)
      blkid -t "UUID=${source#UUID=}" -o device 2>/dev/null | head -n1
      return
      ;;
    LABEL=*)
      blkid -t "LABEL=${source#LABEL=}" -o device 2>/dev/null | head -n1
      return
      ;;
    /dev/*)
      readlink -f "$source" 2>/dev/null || printf '%s\n' "$source"
      return
      ;;
    *)
      printf '%s\n' "$source"
      return
      ;;
  esac
}

resolve_base() {
  local device=$1
  if [ -z "$device" ]; then
    return 1
  fi
  local resolved
  resolved=$(readlink -f "$device" 2>/dev/null || printf '%s\n' "$device")
  local parent
  parent=$(lsblk -no pkname "$resolved" 2>/dev/null || true)
  if [ -n "$parent" ]; then
    printf '/dev/%s\n' "$parent"
  else
    printf '%s\n' "$resolved"
  fi
}

root_source=$(findmnt -no SOURCE / || true)
root_device=$(resolve_source "$root_source" || true)
root_base=$(resolve_base "$root_device" || true)

target_real=$(readlink -f "$TARGET")
target_base=$(resolve_base "$target_real")

if [ -z "$root_device" ] || [ -z "$root_base" ]; then
  die "Unable to determine the active root device" "confirm findmnt output"
fi

if [ "$target_base" = "$root_base" ]; then
  die "Refusing to operate on the boot disk ($target_base)" "set TARGET to a non-boot device"
fi

mapfile -t mounted_parts < <(lsblk -nr -o NAME,MOUNTPOINT "$target_real" | awk '$2 != "" {print "/dev/" $1 " -> " $2}')
if [ "${#mounted_parts[@]}" -gt 0 ]; then
  log "Unmounting ${#mounted_parts[@]} mounted partition(s) on $TARGET"
  for entry in "${mounted_parts[@]}"; do
    part_device=${entry%% -> *}
    mount_point=${entry#* -> }
    if [ -z "$mount_point" ]; then
      continue
    fi
    if umount "$mount_point"; then
      log "[ok] Unmounted $part_device from $mount_point"
    else
      printf '%s: Failed to unmount %s (%s)\n' "$SCRIPT_NAME" "$part_device" "$mount_point" >&2
      printf 'Suggest running: just clean-mounts-hard TARGET=%s\n' "$TARGET" >&2
      exit 1
    fi
  done

  mapfile -t mounted_parts < <(lsblk -nr -o NAME,MOUNTPOINT "$target_real" | awk '$2 != "" {print "/dev/" $1 " -> " $2}')
  if [ "${#mounted_parts[@]}" -gt 0 ]; then
    printf '%s\n' "${SCRIPT_NAME}: Refusing to continue; target partitions are mounted:" >&2
    printf '  %s\n' "${mounted_parts[@]}" >&2
    printf 'Suggest running: just clean-mounts-hard TARGET=%s\n' "$TARGET" >&2
    exit 1
  fi
fi

printf '[ok] Target partitions unmounted\n'

check_signatures() {
  local device=$1
  local output
  output=$(wipefs --noheadings --force --dry-run "$device" 2>/dev/null || true)
  if [ -n "$output" ]; then
    printf '%s\n' "$output"
    return 0
  fi
  return 1
}

signature_devices=()
while IFS= read -r line; do
  signature_devices+=("$line")
done < <(lsblk -nr -o NAME "$target_real" | awk '{print "/dev/" $1}')

signatures_found=0
signature_details=()
for dev in "${signature_devices[@]}"; do
  if sig_out=$(check_signatures "$dev"); then
    signatures_found=1
    signature_details+=("$dev: $sig_out")
  fi
done

if [ "$signatures_found" -eq 1 ] && [ "$WIPE" != "1" ]; then
  printf '%s\n' "${SCRIPT_NAME}: Existing filesystem signatures detected on $TARGET:" >&2
  printf '  %s\n' "${signature_details[@]}" >&2
  printf "Re-run with WIPE=1 to clear the disk.\n" >&2
  exit 1
fi

if [ "$WIPE" = "1" ]; then
  log "WIPE=1 detected; clearing filesystem signatures on $TARGET"
  wipefs -a "$TARGET"
  if [ "$signatures_found" -eq 1 ]; then
    printf '%s\n' "Removed signatures:" >&2
    printf '  %s\n' "${signature_details[@]}" >&2
  fi
fi

root_partuuid=$(blkid -s PARTUUID -o value "$root_device" 2>/dev/null || true)
if [ -z "$root_partuuid" ]; then
  root_partuuid="unknown"
fi

target_size=$(lsblk -nb -o SIZE "$target_real" | head -n1)
root_used=$(df -B1 --output=used / | tail -n1)

if [ -n "$target_size" ] && [ -n "$root_used" ]; then
  if [ "$target_size" -le "$root_used" ]; then
    die "Target $TARGET is smaller than the data on /" "choose a larger disk"
  fi
fi

printf '\n=== SD to NVMe Preflight Checklist ===\n'
printf 'Active root device : %s\n' "$root_device"
printf 'Target device      : %s\n' "$target_real"
printf 'Target size (bytes): %s\n' "$target_size"
printf 'Used on / (bytes)  : %s\n' "$root_used"
printf 'WIPE mode          : %s\n' "$WIPE"
printf '\nNext actions:\n'
printf '  1. Clone: sudo TARGET=%s WIPE=%s just clone-ssd\n' "$TARGET" "$WIPE"
printf '  2. Validate: sudo TARGET=%s just verify-clone\n' "$TARGET"
printf '  3. Cleanup if needed: sudo TARGET=%s just clean-mounts-hard\n' "$TARGET"
printf '\nSafety reminders:\n'
printf '  - Confirm the target is not the active boot device.\n'
printf '  - Ensure backups are up to date before cloning.\n'
printf '\nExpected output:\n'
printf '  [ok] Target partitions unmounted\n'
printf '  [ok] Optional wipe completed (if WIPE=1)\n'
printf '  [ok] Disk size larger than used space on /\n'
