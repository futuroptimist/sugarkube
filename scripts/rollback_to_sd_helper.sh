#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

cat <<'GUIDE'
[rollback-to-sd]
  This helper keeps the current system untouched and shows the exact commands
  to prefer the SD card on next boot.

Steps:
  1. Review current boot sources:
       findmnt -no SOURCE /
  2. Preview the rollback changes (no edits):
       sudo scripts/rollback_to_sd.sh --dry-run
  3. Apply the rollback when ready:
       sudo scripts/rollback_to_sd.sh
  4. Reboot to confirm the Pi boots from the SD card.

To revert back to NVMe afterwards, rerun the clone workflow and verify with:
  sudo TARGET=/dev/nvme0n1 just verify-clone
GUIDE
