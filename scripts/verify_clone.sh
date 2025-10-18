#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_NAME=$(basename "$0")
TARGET=${TARGET:-}
MOUNT_BASE=${MOUNT_BASE:-/mnt/clone}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '%s: missing required command: %s\n' "$SCRIPT_NAME" "$1" >&2
    exit 1
  fi
}

require_cmd findmnt
require_cmd lsblk
require_cmd blkid
require_cmd mount
require_cmd umount
require_cmd fatlabel
require_cmd e2label

if [ -z "$TARGET" ]; then
  printf '%s: TARGET is not set (example: /dev/nvme0n1)\n' "$SCRIPT_NAME" >&2
  exit 1
fi

if [ ! -b "$TARGET" ]; then
  printf '%s: target %s is not a block device\n' "$SCRIPT_NAME" "$TARGET" >&2
  exit 1
fi

partition_path() {
  local base=$1
  local index=$2
  if [[ $base =~ [0-9]$ ]]; then
    printf '%sp%s\n' "$base" "$index"
  else
    printf '%s%s\n' "$base" "$index"
  fi
}

ROOT_PART=$(partition_path "$TARGET" 2)
BOOT_PART=$(partition_path "$TARGET" 1)

if [ ! -b "$ROOT_PART" ]; then
  printf '%s: expected root partition %s not found\n' "$SCRIPT_NAME" "$ROOT_PART" >&2
  exit 1
fi

if [ ! -b "$BOOT_PART" ]; then
  printf '%s: expected boot partition %s not found\n' "$SCRIPT_NAME" "$BOOT_PART" >&2
  exit 1
fi

if findmnt -rn --target "$MOUNT_BASE" >/dev/null 2>&1; then
  printf '%s: %s is already mounted; run just clean-mounts-hard first\n' "$SCRIPT_NAME" "$MOUNT_BASE" >&2
  exit 1
fi

mkdir -p "$MOUNT_BASE"

BOOT_MOUNT_CANDIDATE="$MOUNT_BASE/boot"
if [ -d "$MOUNT_BASE/boot/firmware" ]; then
  BOOT_MOUNT_CANDIDATE="$MOUNT_BASE/boot/firmware"
fi

cleanup() {
  local status=$?
  set +e
  if mountpoint -q "$BOOT_MOUNT_CANDIDATE"; then
    umount "$BOOT_MOUNT_CANDIDATE"
  fi
  if mountpoint -q "$MOUNT_BASE"; then
    umount "$MOUNT_BASE"
  fi
  exit $status
}
trap cleanup EXIT

if ! mount -o ro "$ROOT_PART" "$MOUNT_BASE"; then
  printf '%s: failed to mount %s at %s\n' "$SCRIPT_NAME" "$ROOT_PART" "$MOUNT_BASE" >&2
  exit 1
fi

if [ -d "$MOUNT_BASE/boot/firmware" ]; then
  BOOT_MOUNT_CANDIDATE="$MOUNT_BASE/boot/firmware"
elif [ -d "$MOUNT_BASE/boot" ]; then
  BOOT_MOUNT_CANDIDATE="$MOUNT_BASE/boot"
else
  BOOT_MOUNT_CANDIDATE="$MOUNT_BASE/boot"
fi

if ! mount -o ro "$BOOT_PART" "$BOOT_MOUNT_CANDIDATE"; then
  printf '%s: failed to mount %s at %s\n' "$SCRIPT_NAME" "$BOOT_PART" "$BOOT_MOUNT_CANDIDATE" >&2
  exit 1
fi

ROOT_PARTUUID=$(blkid -s PARTUUID -o value "$ROOT_PART")
BOOT_PARTUUID=$(blkid -s PARTUUID -o value "$BOOT_PART")
ROOT_UUID=$(blkid -s UUID -o value "$ROOT_PART" 2>/dev/null || true)
BOOT_LABEL=$(fatlabel "$BOOT_PART" 2>/dev/null || true)
ROOT_LABEL=$(e2label "$ROOT_PART" 2>/dev/null || true)

RESULTS=()
FAILURES=0

CMDLINE_PATH="$BOOT_MOUNT_CANDIDATE/cmdline.txt"
if [ ! -f "$CMDLINE_PATH" ]; then
  RESULTS+=("[fail] Missing cmdline.txt at $CMDLINE_PATH")
  FAILURES=$((FAILURES + 1))
else
  if grep -Eq "root=PARTUUID=${ROOT_PARTUUID}" "$CMDLINE_PATH"; then
    RESULTS+=("[ok] cmdline.txt references root=PARTUUID=${ROOT_PARTUUID}")
  else
    RESULTS+=("[fail] cmdline.txt does not reference root=PARTUUID=${ROOT_PARTUUID}")
    FAILURES=$((FAILURES + 1))
  fi
fi

FSTAB_PATH="$MOUNT_BASE/etc/fstab"
if [ ! -f "$FSTAB_PATH" ]; then
  RESULTS+=("[fail] Missing fstab at $FSTAB_PATH")
  FAILURES=$((FAILURES + 1))
else
  root_spec=$(awk '$1 !~ /^#/ && $2 == "/" {print $1}' "$FSTAB_PATH" | head -n1)
  boot_spec=$(awk '$1 !~ /^#/ && ($2 == "/boot" || $2 == "/boot/firmware") {print $1}' "$FSTAB_PATH" | head -n1)
  if [ "$root_spec" = "PARTUUID=${ROOT_PARTUUID}" ]; then
    RESULTS+=("[ok] /etc/fstab root entry uses PARTUUID=${ROOT_PARTUUID}")
  else
    RESULTS+=("[fail] /etc/fstab root entry mismatch (expected PARTUUID=${ROOT_PARTUUID}, saw ${root_spec:-none})")
    FAILURES=$((FAILURES + 1))
  fi
  if [ "$boot_spec" = "PARTUUID=${BOOT_PARTUUID}" ]; then
    RESULTS+=("[ok] /etc/fstab boot entry uses PARTUUID=${BOOT_PARTUUID}")
  else
    RESULTS+=("[fail] /etc/fstab boot entry mismatch (expected PARTUUID=${BOOT_PARTUUID}, saw ${boot_spec:-none})")
    FAILURES=$((FAILURES + 1))
  fi
fi

if [ -n "$BOOT_LABEL" ] && [ "$BOOT_LABEL" = "${BOOT_LABEL^^}" ] && [ "$BOOT_LABEL" = "BOOTFS" ]; then
  RESULTS+=("[ok] Boot partition label is BOOTFS")
else
  RESULTS+=("[fail] Boot partition label must be BOOTFS (saw ${BOOT_LABEL:-unset})")
  FAILURES=$((FAILURES + 1))
fi

if [ "$ROOT_LABEL" = "rootfs" ]; then
  RESULTS+=("[ok] Root partition label is rootfs")
else
  RESULTS+=("[fail] Root partition label must be rootfs (saw ${ROOT_LABEL:-unset})")
  FAILURES=$((FAILURES + 1))
fi

printf '\n=== NVMe Clone Validation Report ===\n'
for entry in "${RESULTS[@]}"; do
  printf '%s\n' "$entry"
fi
printf '\nIdentifiers:\n'
printf '  ROOT PARTUUID: %s\n' "$ROOT_PARTUUID"
printf '  ROOT UUID    : %s\n' "${ROOT_UUID:-n/a}"
printf '  BOOT PARTUUID: %s\n' "$BOOT_PARTUUID"
printf '  Boot label   : %s\n' "${BOOT_LABEL:-n/a}"
printf '  Root label   : %s\n' "${ROOT_LABEL:-n/a}"

if [ "$FAILURES" -ne 0 ]; then
  printf '\n%s: validation failed (%d issue(s)).\n' "$SCRIPT_NAME" "$FAILURES" >&2
  printf 'Consider rerunning the clone or repairing configs manually.\n' >&2
  exit 1
fi

printf '\nAll checks passed.\n'
printf 'Expected output:\n'
printf '  [ok] cmdline.txt root PARTUUID\n'
printf '  [ok] fstab boot/root PARTUUID entries\n'
printf '  [ok] Labels: BOOTFS + rootfs\n'
