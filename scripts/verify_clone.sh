#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

TARGET="${TARGET:-}"
MOUNT_BASE="${MOUNT_BASE:-/mnt/clone}"
boot_mount=""

log() {
  printf '[verify-clone] %s\n' "$*"
}

fail_line() {
  local reason="$1"
  local next="$2"
  printf 'verify-clone: %s. Next: %s\n' "$reason" "$next" >&2
}

require_cmd() {
  local binary="$1"
  local package="${2:-$1}"
  if ! command -v "$binary" >/dev/null 2>&1; then
    printf 'verify-clone: missing required command %s. Next: sudo apt-get install -y %s\n' "$binary" "$package" >&2
    exit 1
  fi
}

cleanup() {
  local status=$?
  set +e
  if [[ -n "$boot_mount" ]] && mountpoint -q "$boot_mount" 2>/dev/null; then
    umount "$boot_mount" >/dev/null 2>&1 || umount -l "$boot_mount" >/dev/null 2>&1 || true
  fi
  if mountpoint -q "$MOUNT_BASE" 2>/dev/null; then
    umount "$MOUNT_BASE" >/dev/null 2>&1 || umount -l "$MOUNT_BASE" >/dev/null 2>&1 || true
  fi
  exit "$status"
}

trap cleanup EXIT

require_cmd findmnt util-linux
require_cmd lsblk util-linux
require_cmd blkid util-linux
require_cmd mount util-linux
require_cmd mountpoint util-linux
require_cmd fatlabel dosfstools
require_cmd e2label e2fsprogs

if [[ -z "$TARGET" ]]; then
  printf 'verify-clone: TARGET is not set. Next: export TARGET=/dev/nvme0n1 just verify-clone\n' >&2
  exit 1
fi

if [[ ! -b "$TARGET" ]]; then
  printf 'verify-clone: %s is not a block device. Next: lsblk -d --output NAME,PATH\n' "$TARGET" >&2
  exit 1
fi

mkdir -p "$MOUNT_BASE"

readarray -t partitions < <(lsblk -nr -o PATH,FSTYPE "$TARGET" 2>/dev/null || true)
boot_dev=""
root_dev=""
for entry in "${partitions[@]}"; do
  path=${entry%% *}
  fstype=${entry#* }
  if [[ "$path" == "$TARGET" ]]; then
    continue
  fi
  case "$fstype" in
    vfat|fat32|msdos)
      boot_dev="${boot_dev:-$path}"
      ;;
    ext4)
      root_dev="${root_dev:-$path}"
      ;;
  esac
done

if [[ -z "$boot_dev" ]]; then
  fail_line "unable to detect boot partition on $TARGET" "lsblk -f $TARGET"
  exit 1
fi
if [[ -z "$root_dev" ]]; then
  fail_line "unable to detect root partition on $TARGET" "lsblk -f $TARGET"
  exit 1
fi

log "Mounting $root_dev read-only at $MOUNT_BASE"
mount -t ext4 -o ro,noload "$root_dev" "$MOUNT_BASE"

boot_mount="$MOUNT_BASE/boot/firmware"
if [[ ! -d "$boot_mount" ]]; then
  boot_mount="$MOUNT_BASE/boot"
fi
mkdir -p "$boot_mount"
log "Mounting $boot_dev read-only at $boot_mount"
mount -t vfat -o ro "$boot_dev" "$boot_mount"

cmdline_path="$boot_mount/cmdline.txt"
fstab_path="$MOUNT_BASE/etc/fstab"
if [[ ! -f "$cmdline_path" ]]; then
  fail_line "missing cmdline.txt at $cmdline_path" "rerun clone-ssd to regenerate boot files"
  exit 1
fi
if [[ ! -f "$fstab_path" ]]; then
  fail_line "missing /etc/fstab at $fstab_path" "rerun clone-ssd to regenerate boot files"
  exit 1
fi

root_partuuid=$(blkid -s PARTUUID -o value "$root_dev" 2>/dev/null | tr -d '\n' || true)
root_uuid=$(blkid -s UUID -o value "$root_dev" 2>/dev/null | tr -d '\n' || true)
boot_partuuid=$(blkid -s PARTUUID -o value "$boot_dev" 2>/dev/null | tr -d '\n' || true)
boot_uuid=$(blkid -s UUID -o value "$boot_dev" 2>/dev/null | tr -d '\n' || true)

report=()
errors=()

if [[ -z "$root_partuuid" ]]; then
  report+=('✗ unable to read PARTUUID for root partition')
  errors+=("blkid did not return a PARTUUID for $root_dev|sudo blkid $root_dev")
elif grep -Eq "root=PARTUUID=${root_partuuid}" "$cmdline_path"; then
  report+=('✓ cmdline.txt root=PARTUUID matches target')
else
  report+=('✗ cmdline.txt root=PARTUUID mismatch')
  errors+=("cmdline root entry does not match ${root_partuuid}|sudo sed -i 's#root=PARTUUID=[^ ]*#root=PARTUUID=${root_partuuid}#' $cmdline_path")
fi

boot_rel="boot/firmware"
if [[ "$boot_mount" == "$MOUNT_BASE/boot" ]]; then
  boot_rel="boot"
fi
boot_mountpoint="/${boot_rel}"

root_entry=$(awk 'NF && $1 !~ /^#/ && $2=="/" {print $1; exit}' "$fstab_path")
if [[ -z "$root_entry" ]]; then
  report+=('✗ /etc/fstab missing rootfs entry')
  errors+=("/etc/fstab missing / entry|sudo nano $fstab_path")
else
  expected_root=""
  if [[ -n "$root_partuuid" ]]; then
    expected_root="PARTUUID=${root_partuuid}"
  elif [[ -n "$root_uuid" ]]; then
    expected_root="UUID=${root_uuid}"
  else
    expected_root="(unknown)"
  fi
  if [[ "$root_entry" == "PARTUUID=${root_partuuid}" ]]; then
    report+=('✓ /etc/fstab rootfs uses PARTUUID')
  elif [[ -n "$root_uuid" && "$root_entry" == "UUID=${root_uuid}" ]]; then
    report+=('✓ /etc/fstab rootfs uses UUID')
  else
    report+=('✗ /etc/fstab rootfs entry mismatch')
    errors+=("fstab root entry (${root_entry}) does not reference ${expected_root}|sudo nano $fstab_path")
  fi
fi

boot_entry=$(awk -v mount="$boot_mountpoint" 'NF && $1 !~ /^#/ && $2==mount {print $1; exit}' "$fstab_path")
if [[ -z "$boot_entry" ]]; then
  report+=("✗ /etc/fstab missing ${boot_mountpoint} entry")
  errors+=("/etc/fstab missing ${boot_mountpoint}|sudo nano $fstab_path")
else
  expected_boot=""
  if [[ -n "$boot_partuuid" ]]; then
    expected_boot="PARTUUID=${boot_partuuid}"
  elif [[ -n "$boot_uuid" ]]; then
    expected_boot="UUID=${boot_uuid}"
  else
    expected_boot="(unknown)"
  fi
  if [[ "$boot_entry" == "PARTUUID=${boot_partuuid}" ]]; then
    report+=("✓ /etc/fstab ${boot_mountpoint} uses PARTUUID")
  elif [[ -n "$boot_uuid" && "$boot_entry" == "UUID=${boot_uuid}" ]]; then
    report+=("✓ /etc/fstab ${boot_mountpoint} uses UUID")
  else
    report+=("✗ /etc/fstab ${boot_mountpoint} entry mismatch")
    errors+=("fstab ${boot_mountpoint} entry (${boot_entry}) does not reference ${expected_boot}|sudo nano $fstab_path")
  fi
fi

boot_label_raw=$(fatlabel "$boot_dev" 2>/dev/null || true)
boot_label_clean=$(printf '%s' "$boot_label_raw" | tr -d '\r')
boot_label_trim=$(awk -F"'" 'NF>1 {print $2}' <<<"$boot_label_clean")
boot_label_trim=${boot_label_trim:-$boot_label_clean}
boot_label_trim=$(printf '%s' "$boot_label_trim" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
if [[ -z "$boot_label_trim" ]]; then
  boot_label_trim=$(blkid -s LABEL -o value "$boot_dev" 2>/dev/null | tr -d '\n')
fi
boot_label_upper=$(printf '%s' "$boot_label_trim" | tr '[:lower:]' '[:upper:]')
if [[ -n "$boot_label_trim" && "$boot_label_trim" == "$boot_label_upper" ]]; then
  report+=('✓ boot partition label is uppercase')
else
  report+=('✗ boot partition label is not uppercase')
  errors+=("boot label '${boot_label_trim:-unknown}' should be uppercase (e.g. BOOTFS)|sudo fatlabel $boot_dev BOOTFS")
fi

root_label=$(e2label "$root_dev" 2>/dev/null | tr -d '\n' || true)
if [[ "$root_label" == "rootfs" ]]; then
  report+=('✓ root partition label is rootfs')
else
  report+=("✗ root partition label is '${root_label:-unset}'")
  errors+=("root label '${root_label:-unset}' should be rootfs|sudo e2label $root_dev rootfs")
fi

printf '%s\n' "${report[@]}"

if [[ ${#errors[@]} -gt 0 ]]; then
  for entry in "${errors[@]}"; do
    reason=${entry%%|*}
    suggestion=${entry#*|}
    printf 'verify-clone: %s. Next: %s\n' "$reason" "$suggestion" >&2
  done
  exit 1
fi

log "Validation complete."
