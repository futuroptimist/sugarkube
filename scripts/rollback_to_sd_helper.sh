#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROLLBACK_SCRIPT="${SCRIPT_DIR}/rollback_to_sd.sh"

if [ ! -x "$ROLLBACK_SCRIPT" ]; then
  printf '[rollback-to-sd] Unable to find rollback script at %s\n' "$ROLLBACK_SCRIPT" >&2
  exit 1
fi

printf '\n=== Roll Back to SD (Preview) ===\n'
printf 'This helper shows the exact changes without modifying files.\n'
printf 'When you are ready, run the same command without --dry-run.\n\n'
printf 'Previewing rollback steps:\n'
WIPE=0 "$ROLLBACK_SCRIPT" --dry-run

printf '\nNext steps:\n'
printf '  1. Review the dry-run output above.\n'
printf '  2. Apply the change when ready:\n'
printf '       sudo %s\n' "$ROLLBACK_SCRIPT"
printf '  3. Reboot and confirm the system boots from the SD card:\n'
printf '       findmnt -no SOURCE /\n'
printf '\nExpected output:\n'
printf '  [ok] cmdline.txt and /etc/fstab point to the SD partitions\n'
printf '  [ok] Backup files recorded under /var/log/sugarkube/rollback\n'
