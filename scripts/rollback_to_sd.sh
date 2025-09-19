#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: rollback_to_sd.sh [options]

Revert /boot/cmdline.txt and /etc/fstab to boot from the onboard SD card.

Options:
  --sd-boot-device PATH   Override SD boot partition device (default: /dev/mmcblk0p1)
  --sd-root-device PATH   Override SD root partition device (default: /dev/mmcblk0p2)
  --boot-dir PATH         Path where /boot is mounted (default: /boot)
  --cmdline PATH          Path to cmdline.txt (default: BOOT_DIR/cmdline.txt)
  --fstab PATH            Path to fstab (default: /etc/fstab)
  --report PATH           Write a Markdown report to PATH (default: /boot/sugarkube-rollback-report.md)
  --dry-run               Show actions without modifying files
  -h, --help              Show this help message
USAGE
}

log() {
  printf '==> %s\n' "$*"
}

err() {
  printf 'error: %s\n' "$*" >&2
}

die() {
  err "$1"
  exit "${2:-1}"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing required command: $1"
  fi
}

get_partuuid() {
  local source="$1"
  if [[ "$source" == PARTUUID=* ]]; then
    printf '%s\n' "${source#PARTUUID=}"
    return
  fi
  if [[ "$source" == /dev/* ]]; then
    blkid -s PARTUUID -o value "$source"
    return
  fi
  printf '\n'
}

rewrite_cmdline() {
  local source="$1"
  local target_uuid="$2"
  local tmp

  tmp="$(mktemp)"
  python3 - "$source" "$target_uuid" "$tmp" <<'PYCODE'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
uuid = sys.argv[2]
tmp = pathlib.Path(sys.argv[3])
content = path.read_text()
pattern = re.compile(r"root=PARTUUID=\S+")
if not pattern.search(content):
    print("cmdline.txt does not contain a root=PARTUUID entry", file=sys.stderr)
    sys.exit(1)
updated = pattern.sub(f"root=PARTUUID={uuid}", content, count=1)
tmp.write_text(updated)
PYCODE

  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] Would set root PARTUUID to $target_uuid in $source"
    rm -f "$tmp"
    return
  fi

  mv "$tmp" "$source"
}

rewrite_fstab() {
  local source="$1"
  local boot_uuid="$2"
  local root_uuid="$3"
  local tmp

  tmp="$(mktemp)"
  python3 - "$source" "$boot_uuid" "$root_uuid" "$tmp" <<'PYCODE'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
boot_uuid = sys.argv[2]
root_uuid = sys.argv[3]
tmp = pathlib.Path(sys.argv[4])
lines = path.read_text().splitlines()
updated = []
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        updated.append(line)
        continue
    parts = line.split()
    if len(parts) < 2:
        updated.append(line)
        continue
    mountpoint = parts[1]
    if mountpoint == "/":
        parts[0] = f"PARTUUID={root_uuid}"
        line = "\t".join(parts)
    elif mountpoint == "/boot":
        parts[0] = f"PARTUUID={boot_uuid}"
        line = "\t".join(parts)
    updated.append(line)
tmp.write_text("\n".join(updated) + "\n")
PYCODE

  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] Would update / and /boot PARTUUIDs in $source"
    rm -f "$tmp"
    return
  fi

  mv "$tmp" "$source"
}

write_report() {
  local path="$1"
  local content="$2"

  if [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] Would write rollback report to $path"
    return
  fi

  printf '%s\n' "$content" >"$path"
}

SD_BOOT_DEVICE="/dev/mmcblk0p1"
SD_ROOT_DEVICE="/dev/mmcblk0p2"
BOOT_DIR="/boot"
CMDLINE_FILE=""
FSTAB_FILE="/etc/fstab"
REPORT_PATH="/boot/sugarkube-rollback-report.md"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sd-boot-device)
      [[ $# -ge 2 ]] || die "--sd-boot-device requires a value"
      SD_BOOT_DEVICE="$2"
      shift 2
      ;;
    --sd-root-device)
      [[ $# -ge 2 ]] || die "--sd-root-device requires a value"
      SD_ROOT_DEVICE="$2"
      shift 2
      ;;
    --boot-dir)
      [[ $# -ge 2 ]] || die "--boot-dir requires a value"
      BOOT_DIR="$2"
      shift 2
      ;;
    --cmdline)
      [[ $# -ge 2 ]] || die "--cmdline requires a value"
      CMDLINE_FILE="$2"
      shift 2
      ;;
    --fstab)
      [[ $# -ge 2 ]] || die "--fstab requires a value"
      FSTAB_FILE="$2"
      shift 2
      ;;
    --report)
      [[ $# -ge 2 ]] || die "--report requires a value"
      REPORT_PATH="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "Unknown option: $1"
      ;;
  esac
done

if [ -z "$CMDLINE_FILE" ]; then
  CMDLINE_FILE="$BOOT_DIR/cmdline.txt"
fi

if [ "$DRY_RUN" -ne 1 ] && [ "$(id -u)" -ne 0 ]; then
  die "Run as root or pass --dry-run to preview changes"
fi

require_cmd blkid
require_cmd findmnt
require_cmd python3

if [ ! -b "$SD_BOOT_DEVICE" ]; then
  die "SD boot device not found: $SD_BOOT_DEVICE"
fi
if [ ! -b "$SD_ROOT_DEVICE" ]; then
  die "SD root device not found: $SD_ROOT_DEVICE"
fi
if [ ! -f "$CMDLINE_FILE" ]; then
  die "cmdline file not found: $CMDLINE_FILE"
fi
if [ ! -f "$FSTAB_FILE" ]; then
  die "fstab file not found: $FSTAB_FILE"
fi

SD_BOOT_UUID="$(blkid -s PARTUUID -o value "$SD_BOOT_DEVICE" || true)"
SD_ROOT_UUID="$(blkid -s PARTUUID -o value "$SD_ROOT_DEVICE" || true)"
if [ -z "$SD_BOOT_UUID" ] || [ -z "$SD_ROOT_UUID" ]; then
  die "Unable to read PARTUUIDs for $SD_BOOT_DEVICE or $SD_ROOT_DEVICE"
fi

CURRENT_ROOT_SOURCE="$(findmnt -no SOURCE /)"
CURRENT_BOOT_SOURCE="$(findmnt -no SOURCE "$BOOT_DIR" 2>/dev/null || true)"
CURRENT_ROOT_UUID="$(get_partuuid "$CURRENT_ROOT_SOURCE" || true)"
CURRENT_BOOT_UUID="$(get_partuuid "$CURRENT_BOOT_SOURCE" || true)"

log "Detected SD boot device: $SD_BOOT_DEVICE (PARTUUID=$SD_BOOT_UUID)"
log "Detected SD root device: $SD_ROOT_DEVICE (PARTUUID=$SD_ROOT_UUID)"
if [ -n "$CURRENT_ROOT_SOURCE" ]; then
  log "Current root source: $CURRENT_ROOT_SOURCE"
fi
if [ -n "$CURRENT_ROOT_UUID" ]; then
  log "Current root PARTUUID: $CURRENT_ROOT_UUID"
fi
if [ -n "$CURRENT_BOOT_SOURCE" ]; then
  log "Current boot source: $CURRENT_BOOT_SOURCE"
fi
if [ -n "$CURRENT_BOOT_UUID" ]; then
  log "Current boot PARTUUID: $CURRENT_BOOT_UUID"
fi

BACKUP_DIR="/var/log/sugarkube/rollback/$(date -u +%Y%m%dT%H%M%SZ)"
if [ "$DRY_RUN" -eq 1 ]; then
  log "[dry-run] Would create backup directory $BACKUP_DIR"
else
  mkdir -p "$BACKUP_DIR"
fi

backup_file "$CMDLINE_FILE" "$BACKUP_DIR/cmdline.txt"
backup_file "$FSTAB_FILE" "$BACKUP_DIR/fstab"

rewrite_cmdline "$CMDLINE_FILE" "$SD_ROOT_UUID"
rewrite_fstab "$FSTAB_FILE" "$SD_BOOT_UUID" "$SD_ROOT_UUID"

if [ "$DRY_RUN" -ne 1 ]; then
  sync
fi

timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
read -r -d '' REPORT <<EOF_REPORT || true
# Sugarkube SD Rollback

- Timestamp: $timestamp UTC
- Backup directory: $BACKUP_DIR
- Previous root source: ${CURRENT_ROOT_SOURCE:-unknown}
- Previous root PARTUUID: ${CURRENT_ROOT_UUID:-unknown}
- Previous boot source: ${CURRENT_BOOT_SOURCE:-unknown}
- Previous boot PARTUUID: ${CURRENT_BOOT_UUID:-unknown}
- Target SD boot PARTUUID: $SD_BOOT_UUID
- Target SD root PARTUUID: $SD_ROOT_UUID
- Updated files:
  - $CMDLINE_FILE
  - $FSTAB_FILE

Next steps:
1. Reboot the Raspberry Pi.
2. Confirm the system is running from the SD card with `findmnt /`.
3. Investigate SSD health before attempting another migration.
EOF_REPORT

write_report "$REPORT_PATH" "$REPORT"

log "Rollback complete. Reboot to finish applying changes."
if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry run complete; no files were changed."
else
  log "Report written to $REPORT_PATH"
fi
