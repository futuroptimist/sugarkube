# SD to NVMe migration workflow

> [!IMPORTANT]
> Safety rails:
> - Never run preflight or clone tasks with `TARGET` pointing at the active root device. Confirm with `findmnt -no SOURCE /` before you begin.
> - Use `WIPE=1` only on first-time clones or when intentionally re-initialising a reused disk. Every other run should omit it to avoid destructive wipes.
> - Always run verification before rebooting. The helpers refuse to continue when the target partitions are mounted or when identifiers do not match, preventing partial migrations.

## Core path

### 1. Preflight the target disk

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just preflight
```

This checks that the NVMe drive is offline, not the active root device, and, when `WIPE=1`, clears old filesystem signatures. The helper prints a concise checklist of the next steps so you can confirm each stage before committing to a clone.

**Expected output**
- Active root source and target device path listed on a single screen.
- Confirmation that signatures were cleared (or skipped if none were found).
- Checklist showing the follow-on commands (`clone-ssd`, `verify-clone`, `finalize-nvme`, `clean-mounts-hard`).
- A non-zero exit with a single-line remediation hint if the target is mounted or matches the boot device.

### 2. Clone the running system to NVMe

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
```

The wrapper runs `scripts/clone_to_nvme.sh`, invoking `rpi-clone` with unattended flags for first-time initialisation, rewriting `cmdline.txt` and `/etc/fstab`, and syncing `/boot` and `/`. On repeated runs omit `WIPE=1` to keep existing data intact.

**Expected output**
- `rpi-clone` progress including the initial `dd` header, `mkfs`, and `rsync` stages.
- Final summary with bytes transferred and the new PARTUUID/label values.
- Log stored under `artifacts/clone-to-nvme.log` for post-run review.

### 3. Validate the clone before rebooting

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just verify-clone
```

Validation mounts the NVMe clone read-only, inspects `cmdline.txt`, `/etc/fstab`, FAT/ext4 labels, and ensures they reference the NVMe identifiers. All mounts are released automatically on success or failure.

**Expected output**
- A checklist of ✓/✗ results covering `cmdline.txt`, `/etc/fstab`, and partition labels.
- On success, the script exits 0 after printing `Validation complete.`
- On failure, each ✗ line is paired with a single-line remediation command (for example, the exact `sed`/`fatlabel` command to apply).

## Optional helpers

### Show disks at a glance

```bash
just show-disks
```

Lists block devices, UUIDs, PARTUUIDs, and mountpoints so you can double-check the source SD card (`mmcblk0`) versus the NVMe target. Use this snapshot during acceptance tests to prove both devices are visible.

### Aggressive mount cleanup

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just clean-mounts-hard
```

Runs the enhanced cleanup helper with `--force`, recursively unmounting `/mnt/clone`, lazily detaching stubborn mounts, printing PIDs via `fuser`, and removing empty directories under the mount base. The trap guarantees cleanup even when the script exits early.

### Finalise NVMe boot order

```bash
sudo just finalize-nvme
```

Prints the current EEPROM `BOOT_ORDER`, the recommended value (`0xF416`, prioritising NVMe → USB → SD), and opens `rpi-eeprom-config --edit` in your `$EDITOR` with inline guidance. Save and exit to apply, then confirm with `sudo rpi-eeprom-config | grep BOOT_ORDER`.

### Roll back to SD without changes

```bash
just rollback-to-sd
```

Displays the exact dry-run and apply commands for `scripts/rollback_to_sd.sh`. The helper never edits files; it simply guides you through preferring the SD card on the next boot.

## Reference snippets

Use these one-liners during troubleshooting or acceptance testing:

```bash
# Show filesystem metadata
lsblk --fs

# Inspect detailed identifiers
blkid /dev/nvme0n1p2

# Confirm the active root source (should remain mmcblk0 while cloning)
findmnt -no SOURCE /
```

### Understanding BOOT_ORDER

The Raspberry Pi 4/5 bootloader checks devices in the order defined by `BOOT_ORDER` (hex). `0xF416` prioritises NVMe, then USB, then SD, before repeating. Inspect the current setting safely with:

```bash
sudo rpi-eeprom-config | grep BOOT_ORDER
```

If the NVMe disk is not first, run `just finalize-nvme` to review and edit the EEPROM configuration interactively. The helper never applies changes silently and includes inline instructions inside your editor session.
