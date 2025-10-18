# SD to NVMe cloning workflow

Safely migrate a Raspberry Pi that currently boots from SD to an NVMe drive and validate the
result. The flow is idempotent and can be repeated after reboots to confirm nothing drifted.

> **Safety rails**
>
> - Never run destructive commands with `TARGET` equal to your active root device. Confirm with
>   `findmnt -no SOURCE /` first.
> - Only enable `WIPE=1` for first-time initialization or when re-initializing a reused disk. Pair it
>   with `WIPE_CONFIRM=1` so `wipefs` only runs when explicitly authorised.
> - Prefer `PARTUUID` identifiers for the root filesystem in both `cmdline.txt` and `/etc/fstab` to
>   avoid device-name drift.
> - Keep the boot partition label upper-case (for example `BOOTFS`) and the root partition label set
>   to `rootfs`.

## Core workflow

### 1. Preflight

Sanity-check the target NVMe disk, confirm it is not mounted, and (optionally) wipe stale
signatures before cloning.

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 WIPE_CONFIRM=1 just preflight
```

Expected output:

- Clear summary listing the source root/boot devices, target disk metadata, and wipe status.
- Error if any `nvme0n1` partitions are mounted or if it matches the currently booted device.
- Checklist of follow-up steps: `clone-ssd`, `verify-clone`, and `finalize-nvme`.

### 2. Clone from SD

Use the existing cloning helper to mirror the SD card onto the prepared NVMe disk. The command is
safe to rerun; the first pass should include `WIPE=1` to initialise a new disk.

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
```

Expected output:

- `rpi-clone` log showing the device header copy (`dd`), filesystem creation, and rsync.
- No references to the active root device being rewritten.

### 3. Validate the clone

Mount the cloned partitions read-only and assert that bootloader, `cmdline.txt`, and `/etc/fstab`
all reference the NVMe identifiers.

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just verify-clone
```

Expected output:

- Confirmation that `cmdline.txt` contains `root=PARTUUID=<nvme-root-partuuid>`.
- `/etc/fstab` entries for `/` and `/boot` (or `/boot/firmware`) reference the NVMe partition
  identifiers.
- Labels reported as `BOOTFS` (or another uppercase string) and `rootfs`.
- Mount points cleaned up automatically even if a check fails.

## Optional helpers

### Inspect devices quickly

```bash
just show-disks
```

Use this before and after cloning to confirm which device maps to the SD card (typically `mmcblk0`)
and which maps to the NVMe drive. The listing includes `PARTUUID`, filesystem labels, and active
mountpoints.

### Aggressive mount cleanup

```bash
sudo TARGET=/dev/nvme0n1 MOUNT_BASE=/mnt/clone just clean-mounts-hard
```

This recursively unmounts `${MOUNT_BASE}`, attempts a lazy unmount if busy, removes empty
`${MOUNT_BASE}/boot*` directories, and prints any PIDs still holding files.

### Finalise NVMe boot preference

```bash
sudo just finalize-nvme
```

The helper prints the current EEPROM `BOOT_ORDER`, recommends `0xF416` (NVMe → USB → SD), and opens
`rpi-eeprom-config --edit` with inline guidance when a change is required. It never mutates EEPROM
settings silently.

### Roll back to SD on the next boot

```bash
just rollback-to-sd
```

This prints the exact `cmdline.txt` and `/etc/fstab` adjustments needed to prefer the SD card
without applying them automatically. Rerun the underlying script without `--dry-run` if you need to
commit the rollback.

## Reference snippets

Grab common identifiers quickly while diagnosing issues:

- Active root source: `findmnt -no SOURCE /`
- Filesystem metadata: `lsblk --fs`
- Partition identifiers: `blkid -s PARTUUID -o value /dev/nvme0n1p2`
- Check bootloader order safely: `sudo rpi-eeprom-config`

## Acceptance checklist

Automate or spot-check these tasks after changes to the workflow:

1. `just show-disks` displays both the SD source and NVMe target with mountpoints and `PARTUUID`s.
2. `just preflight TARGET=/dev/nvme0n1` exits non-zero if `TARGET` matches `findmnt -no SOURCE /`.
3. A first-time clone (`WIPE=1`) logs the `dd` header copy followed by mkfs/rsync from `rpi-clone`.
4. `just verify-clone TARGET=/dev/nvme0n1` succeeds immediately after cloning and again after a
   reboot.
5. `just clean-mounts-hard` leaves no mounts under `${MOUNT_BASE}` and reports any blocking PIDs.
6. `just finalize-nvme` prints the current `BOOT_ORDER` and guides manual edits; it never applies a
   change silently.
