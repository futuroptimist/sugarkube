# Raspberry Pi 5 Image Spot Check (Bookworm)

Use this playbook immediately after flashing a Raspberry Pi 5 image. The new
`scripts/spot_check.sh` task captures a JSON + Markdown summary under
`artifacts/spot-check/` and fails fast when required checks are out of bounds.

```bash
cd ~/sugarkube
sudo just spot-check
```

The console output lists each section with ✅/⚠️/❌ markers; the same information is
mirrored in `artifacts/spot-check/summary.{json,md}` for archival.

## Required success criteria

| Area | Expectation |
|------|-------------|
| OS & kernel | Raspberry Pi OS Bookworm (12), kernel ≥ 6.12, `aarch64` arch |
| Time & locale | `timedatectl` NTP synchronized, timezone populated, `LANG` set |
| Storage | `/boot/firmware` on `/dev/mmcblk0p1`, `/` on `/dev/mmcblk0p2`, UUIDs captured |
| Networking | Gateway + `1.1.1.1` pings succeed with 0% loss |
| Boot logs | `journalctl -b -p3` free of surprises (Bluetooth init + `bgscan simple`
  noise is auto-ignored) |
| Health | `vcgencmd measure_temp` < 60 °C at idle, `free` shows > 7 Gi available,
  `vcgencmd get_throttled` = `0x0` |

Warnings (⚠️) do not fail the command. For example, link speed < 1000 Mb/s or missing
optional repos trigger warnings with guidance.

## Sample output

```
=== Raspberry Pi 5 Bookworm spot check ===
✅ System baseline: OS=Raspberry Pi OS (64-bit); kernel=6.12.5; arch=aarch64
✅ Time & locale: NTP=yes; TZ=America/Los_Angeles; LANG=en_US.UTF-8
✅ Storage layout: /boot/firmware=/dev/mmcblk0p1; /=/dev/mmcblk0p2
✅ Networking: LAN loss=0%; LAN avg=0.4ms; WAN loss=0%; WAN avg=17.2ms
⚠️ Link speed: eth0=100Mb/s; expected >= 1000Mb/s
✅ Service inventory: No flywheel/k3s/cloudflared/containerd services
✅ Boot errors: Only benign Bluetooth/bgscan messages observed
✅ System health: temp=42.3°C; available=7564MiB; throttled=0x0
ℹ️ Repo sync: sugarkube/dspace/token.place present
✅ Spot check complete. Artifacts: /home/pi/sugarkube/artifacts/spot-check
```

If any required check fails, the script exits non-zero and prints the artifact path for
deeper investigation. Capture `artifacts/spot-check/` in the build report before moving
on.

## Known benign noise

* `bluetoothd` plugin initialization failures when the radio is disabled.
* `wpa_supplicant` `bgscan simple` warnings on idle Wi-Fi interfaces.

These lines are filtered from the error tally but remain in the `spot-check.log` for
transparency.

## Next steps: clone to NVMe

Follow these required steps immediately after the spot check to migrate the boot media.

> [!TIP] Before you start
> - Skip the boot-order step if `sudo rpi-eeprom-config | grep BOOT_ORDER` already shows `0xf461`.
> - Skip ahead to **Step 3** if `lsblk` already lists NVMe boot and root partitions.

### Step 1. Align the boot order (if needed)

Prefer **SD → NVMe → USB → repeat** so the SD card remains your fallback.

```bash
sudo just boot-order sd-nvme-usb
```

The helper prints the resulting EEPROM state. Pass `PCIE_PROBE=1` only when an adapter requires it:

```bash
sudo PCIE_PROBE=1 just boot-order nvme-first
```

### Step 2. Clone the SD card to NVMe

The `clone-ssd` helper wraps `rpi-clone`, installs it on first use, captures logs under
`artifacts/clone-to-nvme.log`, and fixes the cloned `cmdline.txt`/`fstab` entries. Pass the target
device explicitly during the first run so the script can initialise the NVMe layout:

```bash
sudo TARGET=/dev/nvme0n1 WIPE=1 just clone-ssd
```

If a prior run left mounts behind, clean them up before retrying:

```bash
sudo just clean-mounts -- --verbose
```

> [!TIP]
> The `clean-mounts` recipe unmounts any leftover clone targets and removes the automount
> directories (`/mnt/clone` by default). Override `TARGET` or `MOUNT_BASE` if your layout differs:
>
> ```bash
> sudo TARGET=/dev/nvme1n1 MOUNT_BASE=/media/clone just clean-mounts
> ```
>
> Re-run `clone-ssd` once the cleanup completes.

Subsequent syncs only need the target argument:

```bash
sudo TARGET=/dev/nvme0n1 just clone-ssd
```

Bookworm mounts the boot FAT volume at `/boot/firmware`; older images may use `/boot`. The helper
handles both.

### Step 3. Validate the clone while still on SD

- Confirm the expected block devices are present: `lsblk -o NAME,MOUNTPOINT,SIZE,PARTUUID`
- Ensure `PARTUUID` entries in `/boot/firmware/cmdline.txt` and `/etc/fstab` point to the NVMe
  partitions
- Review `sudo vclog -m tip | tail` for a clean boot summary without lingering overrides
- Check `artifacts/clone-to-nvme.log` for the final `rsync` summary and any warnings

## Optional helpers

### Automate the migration (optional)

To chain the spot check, boot-order alignment, clone, and reboot, use:

```bash
sudo just migrate-to-nvme
```

Check `artifacts/migrate-to-nvme/` for the run log if anything looks off.

### One-time SD override (optional)

Keep the NVMe plugged in while testing a fresh SD image by issuing a single-use boot override:

```bash
sudo rpi-eeprom-config --set 'set_reboot_order=0xf1'
```

The Pi will prefer the SD card for the next reboot only, then revert to the configured EEPROM order.

### Troubleshooting the clone (optional)

Mount the clone and inspect the boot files when something fails early:

```bash
sudo mount /dev/nvme0n1p1 /mnt/clone
sudo sed -n '1,120p' /mnt/clone/cmdline.txt
sudo sed -n '1,120p' /mnt/clone/etc/fstab
sudo umount /mnt/clone
```

## Finish: boot from NVMe

1. Shut down cleanly to avoid filesystem damage:

   ```bash
   sudo shutdown -h now
   ```

2. Remove the SD card once the activity LED stops blinking.
3. Power the Raspberry Pi back on so it boots from the cloned NVMe install.
4. Verify the root filesystem now points to the NVMe device:

   ```bash
   findmnt -no SOURCE /
   ```

   Expect an `nvme0n1p2` (or similar) source.
5. Continue with the [k3s cluster setup guide](./raspi_cluster_setup.md) to configure the node.
