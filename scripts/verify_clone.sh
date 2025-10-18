#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

TARGET=${TARGET:-}
MOUNT_BASE=${MOUNT_BASE:-/mnt/clone}
BOOT_SUBDIR=""

log() {
  printf '[verify-clone] %s\n' "$*"
}

fail() {
  printf '[verify-clone] error: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command '$1' is missing"
  fi
}

require_cmd findmnt
require_cmd mount
require_cmd blkid
require_cmd fatlabel
require_cmd e2label

if [[ -z "$TARGET" ]]; then
  fail "Set TARGET (e.g. /dev/nvme0n1) before running verify-clone"
fi

if [[ "$TARGET" != /dev/* ]]; then
  TARGET="/dev/${TARGET}"
fi

if [[ ! -b "$TARGET" ]]; then
  fail "Target $TARGET is not a block device"
fi

cleanup() {
  local status=$?
  trap - EXIT

  if [[ -n "$BOOT_SUBDIR" ]] && findmnt -rn --target "$BOOT_SUBDIR" >/dev/null 2>&1; then
    umount "$BOOT_SUBDIR" 2>/dev/null || umount -l "$BOOT_SUBDIR" 2>/dev/null || true
  fi

  if findmnt -rn --target "$MOUNT_BASE" >/dev/null 2>&1; then
    umount "$MOUNT_BASE" 2>/dev/null || umount -l "$MOUNT_BASE" 2>/dev/null || true
  fi

  exit $status
}
trap cleanup EXIT

mkdir -p "$MOUNT_BASE"

root_part="${TARGET}p2"
boot_part="${TARGET}p1"

if [[ ! -b "$root_part" || ! -b "$boot_part" ]]; then
  fail "Expected ${TARGET}p1 and ${TARGET}p2 to exist"
fi

log "Mounting $root_part read-only at $MOUNT_BASE"
mount -o ro "$root_part" "$MOUNT_BASE"

if [[ -d "$MOUNT_BASE/boot/firmware" ]]; then
  BOOT_SUBDIR="$MOUNT_BASE/boot/firmware"
elif [[ -d "$MOUNT_BASE/boot" ]]; then
  BOOT_SUBDIR="$MOUNT_BASE/boot"
else
  fail "Unable to locate boot mount directory inside $MOUNT_BASE"
fi

log "Mounting $boot_part read-only at $BOOT_SUBDIR"
mount -o ro "$boot_part" "$BOOT_SUBDIR"

root_partuuid=$(blkid -s PARTUUID -o value "$root_part" 2>/dev/null || true)
boot_partuuid=$(blkid -s PARTUUID -o value "$boot_part" 2>/dev/null || true)
root_uuid=$(blkid -s UUID -o value "$root_part" 2>/dev/null || true)
boot_uuid=$(blkid -s UUID -o value "$boot_part" 2>/dev/null || true)

if [[ -z "$root_partuuid" || -z "$boot_partuuid" ]]; then
  fail "Unable to read PARTUUIDs for $TARGET"
fi

cmdline_path=""
for candidate in \
  "$BOOT_SUBDIR/cmdline.txt" \
  "$MOUNT_BASE/boot/cmdline.txt" \
  "$MOUNT_BASE/boot/firmware/cmdline.txt"; do
  if [[ -f "$candidate" ]]; then
    cmdline_path="$candidate"
    break
  fi
done

if [[ -z "$cmdline_path" ]]; then
  fail "cmdline.txt not found in cloned boot partition"
fi

cmdline_content=$(<"$cmdline_path")
if ! grep -Eq "root=PARTUUID=${root_partuuid}" <<<"$cmdline_content"; then
  fail "cmdline.txt does not reference root=PARTUUID=${root_partuuid}"
fi

fstab_path="$MOUNT_BASE/etc/fstab"
if [[ ! -f "$fstab_path" ]]; then
  fail "Missing $fstab_path on cloned root"
fi

root_entry=""
boot_entry=""
while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  read -r spec mountpoint rest <<<"$line"
  case "$mountpoint" in
    /)
      root_entry="$line"
      ;;
    /boot|/boot/firmware)
      boot_entry="$line"
      ;;
  esac
done <"$fstab_path"

if [[ -z "$root_entry" ]]; then
  fail "fstab missing entry for /"
fi
if [[ -z "$boot_entry" ]]; then
  fail "fstab missing entry for /boot or /boot/firmware"
fi

root_spec=$(awk '{print $1}' <<<"$root_entry")
boot_spec=$(awk '{print $1}' <<<"$boot_entry")

validate_spec() {
  local expected_partuuid="$1"
  local expected_uuid="$2"
  local spec="$3"
  local label="$4"

  if [[ "$spec" == PARTUUID=* ]]; then
    local value=${spec#PARTUUID=}
    [[ "$value" == "$expected_partuuid" ]] || fail "$label entry references PARTUUID=$value (expected $expected_partuuid)"
    return 0
  fi

  if [[ "$spec" == UUID=* ]]; then
    local value=${spec#UUID=}
    if [[ -z "$expected_uuid" ]]; then
      fail "$label entry uses UUID= but the target device has no UUID"
    fi
    [[ "$value" == "$expected_uuid" ]] || fail "$label entry references UUID=$value (expected $expected_uuid)"
    return 0
  fi

  fail "$label entry must use PARTUUID= or UUID=, found '$spec'"
}

validate_spec "$root_partuuid" "$root_uuid" "$root_spec" "root"
validate_spec "$boot_partuuid" "$boot_uuid" "$boot_spec" "boot"

boot_label=$(fatlabel "$boot_part" 2>/dev/null | tr -d '\n')
if [[ -z "$boot_label" ]]; then
  fail "Unable to read FAT label for $boot_part"
fi
if [[ "$boot_label" != "${boot_label^^}" ]]; then
  fail "Boot partition label must be upper-case (current: $boot_label)"
fi

root_label=$(e2label "$root_part" 2>/dev/null || true)
if [[ -z "$root_label" ]]; then
  fail "Unable to read ext4 label for $root_part"
fi
if [[ "$root_label" != "rootfs" ]]; then
  fail "Root partition label should be 'rootfs' (current: $root_label)"
fi

printf '\n[verify-clone] Validation summary\n'
printf '  cmdline.txt:  root=PARTUUID=%s\n' "$root_partuuid"
printf '  fstab (/):   %s\n' "$root_spec"
printf '  fstab (boot):%s\n' "$boot_spec"
printf '  BOOT label:  %s\n' "$boot_label"
printf '  root label:  %s\n' "$root_label"

log "All checks passed"
