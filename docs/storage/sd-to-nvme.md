# SD to NVMe Migration

A minimal, repeatable workflow for cloning the active SD card to NVMe storage on
Raspberry Pi 4/5 hardware. Each step is safe to rerun and designed to stop
before touching the booted disk.

## Safety rails

> [!CAUTION]
> * Never set `TARGET` to the device backing `/` (check with `findmnt -no SOURCE /`).
> * Use `WIPE=1` only when initializing a new disk or intentionally reusing an
>   existing target—this clears filesystem signatures with `wipefs -a`.
> * Run every command with `sudo` unless your environment is pre-configured for
>   passwordless privilege escalation.

## Core path

### 1. Preflight the target disk

Confirm the target is not the boot device, unmount any lingering partitions, and
optionally wipe signatures on first use.

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just preflight
```

Expected output:

- `[ok]` Target partitions are unmounted.
- `[ok]` Optional wipe completed when `WIPE=1`.
- `[ok]` Target capacity exceeds the used space on `/`.

> Regression coverage: `tests/test_preflight_clone.py::test_preflight_unmounts_mounted_partitions`
> confirms the helper automatically unmounts lingering partitions before
> continuing.

### 2. Clone the active SD card

Run the unattended clone. Keep `WIPE=1` set the first time you prepare a fresh
disk.

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
```

Expected output:

- `rpi-clone` logs show partitioning, formatting, and `rsync` copy progress.
- `[ok]` Final summary reports `Clone completed` without errors.
- `[ok]` `/var/log/sugarkube/clone-to-nvme.log` exists for review.

### 3. Validate the NVMe clone

Mount the NVMe partitions read-only and confirm boot identifiers match.

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just verify-clone
```

Expected output:

- `[ok]` `cmdline.txt` references `root=PARTUUID=...` for the NVMe root.
- `[ok]` `/etc/fstab` uses NVMe `PARTUUID` values for `/` and `/boot`.
- `[ok]` Partition labels read `BOOTFS` (FAT) and `rootfs` (ext4).

After validation, reboot once to confirm the system boots cleanly from NVMe and
runs `just verify-clone` again for idempotence.

## Optional helpers

### Show all block devices

```bash
just show-disks
```

Outputs a single-page summary (`lsblk -e7`) highlighting device sizes, UUIDs,
and mountpoints so you can double-check the `TARGET` assignment.

### Aggressive mount cleanup

If mounts linger from an interrupted run, tear them down:

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just clean-mounts-hard
```

The helper recursively unmounts `${MOUNT_BASE}`, lazily detaches busy mounts as a
last resort, prints blocking PIDs via `fuser -vm`, and removes empty
`${MOUNT_BASE}/boot*` directories.

### Finalize NVMe boot priority

Inspect the EEPROM boot configuration and open an editor when NVMe is not first
in the boot sequence.

```bash
sudo FINALIZE_NVME_EDIT=1 just finalize-nvme
```

The script reads `BOOT_ORDER` via `rpi-eeprom-config --config`, recommends
`0xF416` (NVMe → USB → SD → repeat), and—when edits are required—launches
`rpi-eeprom-config --edit` with reminders to save the change explicitly.

### Roll back to the SD card

Preview the commands needed to prefer the SD card on the next boot:

```bash
just rollback-to-sd
```

The helper runs `rollback_to_sd.sh --dry-run`, prints the exact modifications
without applying them, and lists the follow-up commands to execute manually.

## Reference snippets

Quick commands to gather identifiers when troubleshooting:

```bash
findmnt -no SOURCE /
lsblk --fs
blkid -s PARTUUID -o value /dev/nvme0n1p2
```

### Boot order primer

`rpi-eeprom-config --config | grep BOOT_ORDER` prints the active EEPROM boot
sequence. Each nibble represents a boot medium (`0x4` = NVMe/PCIe, `0x1` = SD,
`0x6` = USB mass storage). Setting `BOOT_ORDER=0xF416` tries NVMe first, falls
back to USB, then SD, and finally repeats. Always edit via `sudo -E
rpi-eeprom-config --edit` so you can review changes before saving.
