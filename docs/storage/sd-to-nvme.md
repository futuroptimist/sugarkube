# SD → NVMe cloning workflow

> **Safety rails**
> - Never run the clone pipeline against the disk that is currently hosting `/`.
> - Use `WIPE=1` only for first-time initialization or when you deliberately want to reformat a reused NVMe drive.
> - Always double-check identifiers with `just show-disks` before touching block devices.

The workflow is designed to be idempotent: you can rerun any step without leaving partially mounted filesystems behind. Each task assumes you run it with `sudo --preserve-env` as shown below.

## Core path

### 1. Preflight the target NVMe

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just preflight
```

Expected output:
- The active root device (typically `/dev/mmcblk0p2`) is shown alongside the target NVMe disk.
- Any mounted partitions on the target cause the task to abort with a pointer to `just clean-mounts-hard`.
- When `WIPE=1`, `wipefs -a` runs once to clear conflicting signatures and the checklist highlights the clean state.

### 2. Clone the SD card to NVMe

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
```

Expected output:
- `rpi-clone` streams the SD contents to the NVMe drive (first run uses the unattended `-U` fallback).
- `/boot/cmdline.txt` and `/etc/fstab` on the clone are rewritten to use `PARTUUID`/`UUID` entries for the NVMe partitions.
- The summary line shows the resolved identifiers for the cloned boot and root partitions.

### 3. Validate the clone

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just verify-clone
```

Expected output:
- The script mounts the NVMe root under `/mnt/clone` and the boot partition under `/mnt/clone/boot` or `/mnt/clone/boot/firmware`.
- The validation report lists each check (cmdline, fstab, labels) as `[PASS]` or `[FAIL]`.
- Labels are confirmed as `BOOTFS` (FAT) and `rootfs` (ext4); any mismatch leaves the mounts in place so you can inspect before rerunning `just clean-mounts-hard`.

## Optional helpers

### Snapshot disks and mountpoints

```bash
just show-disks
```

Displays `lsblk -e7 -o NAME,MAJ:MIN,SIZE,TYPE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS` so you can confirm source (SD) and target (NVMe) devices before cloning.

### Aggressive mount cleanup

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just clean-mounts-hard
```

Performs `umount -R`, falls back to lazy unmounts if needed, prints blocking PIDs via `fuser`, and removes only empty mount directories. Use this to recover from interrupted validations or manual tweaks.

### Finalize NVMe boot priority

```bash
sudo just finalize-nvme
```

Reads the EEPROM bootloader configuration (Pi 4/5). If the current `BOOT_ORDER` is not `0xF416`, it launches `rpi-eeprom-config --edit` with inline guidance so you can update the value manually. After saving, it prints the new order and a reminder to confirm with `sudo rpi-eeprom-config | grep BOOT_ORDER`.

### Roll back to the SD card

```bash
just rollback-to-sd
```

Prints a reversible plan that:
1. Runs `scripts/rollback_to_sd.sh --dry-run` so you can preview the changes.
2. Shows the exact commands to restore `cmdline.txt` and `/etc/fstab` to the SD defaults.
3. Points to `sudo just boot-order sd-nvme-usb` so the EEPROM prefers the SD card on the next boot.

## Reference snippets

- List filesystem identifiers: `lsblk --fs` or `blkid`
- Confirm the active root device: `findmnt -no SOURCE /`
- Inspect BOOT_ORDER without editing: `sudo rpi-eeprom-config | grep BOOT_ORDER`

`BOOT_ORDER` controls the sequence the Pi bootloader tries devices. `0xF416` means “NVMe → SD → USB → repeat,” while `0xF461` prefers “SD → NVMe → USB → repeat.”

## Acceptance checks

- `just show-disks` lists the SD (`mmcblk0`) and NVMe (`nvme0n1`) devices with their PARTUUIDs and mountpoints.
- `just preflight TARGET=/dev/nvme0n1` fails fast if `TARGET` matches the active root device reported by `findmnt -no SOURCE /`.
- A first-time clone with `WIPE=1` logs the `rpi-clone` initialization path (`dd` header followed by `mkfs` and `rsync`).
- `just verify-clone TARGET=/dev/nvme0n1` succeeds immediately after cloning and again after a reboot.
- `just clean-mounts-hard` leaves no mounts under `$MOUNT_BASE` and prints any blocking PIDs before exiting.
- `just finalize-nvme` reports the current `BOOT_ORDER` and opens an interactive editor instead of applying firmware changes silently.
