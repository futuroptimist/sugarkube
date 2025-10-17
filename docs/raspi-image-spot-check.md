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

With the SD image validated:

> [!TIP] Before you start
> - Run `sudo just boot-order print`. If it already shows `BOOT_ORDER=0xf461`, you can skip the Boot-Order step.
> - Check the NVMe layout with `lsblk -o NAME,SIZE,TYPE,MOUNTPOINT /dev/nvme0n1`. If you already see boot (`p1`) and root (`p2`) partitions with recent timestamps, skip the initialization command and jump to the verification checklist.

1. **Align the boot order (SD → NVMe → USB).** This keeps the SD card first for recovery but promotes NVMe for normal boots.
   ```bash
   sudo just boot-order sd-nvme-usb
   ```
   - Some USB-to-NVMe bridges require `PCIE_PROBE=1`; opt-in with `PCIE_PROBE=1 sudo just boot-order sd-nvme-usb` when needed.

2. **Initialize and clone the NVMe drive.** `rpi-clone`'s `-U` flag is required the very first time to create the partition table and enable filesystem UUID swaps.
   ```bash
   sudo rpi-clone -f -U /dev/nvme0n1
   ```
   - After the first initialization, reruns are idempotent via `sudo just clone-ssd TARGET=/dev/nvme0n1` (add `WIPE=1` when you want a fresh copy).

3. **Happy-path automation (optional).** `migrate-to-nvme` chains the spot check, boot-order preset, clone, and reboot.
   ```bash
   sudo just migrate-to-nvme
   ```
   - Set `SKIP_EEPROM=1` if you already set the boot order, and `NO_REBOOT=1` when you need to delay the reboot.

4. **Post-clone validation.** Whether you used the manual or automated path, run the verification helper.
   ```bash
   sudo just post-clone-verify
   ```

> [!TIP] Troubleshooting clone artifacts
> - Create the mountpoints: `sudo mkdir -p /mnt/clone /mnt/clone/boot`.
> - Mount the NVMe root and boot partitions: `sudo mount /dev/nvme0n1p2 /mnt/clone` and `sudo mount /dev/nvme0n1p1 /mnt/clone/boot`.
> - Inspect `/mnt/clone/boot/cmdline.txt` and `/mnt/clone/etc/fstab` for the expected `PARTUUID`s.
> - When finished, unmount with `sudo umount /mnt/clone/boot /mnt/clone`.

To test a brand-new SD card while the NVMe remains attached, issue a one-time override:

```bash
sudo rpi-eeprom-config --set set_reboot_order=0xf1
```

The bootloader will prefer the SD card on the next reboot only and then fall back to the normal sequence.

### Verification checklist

- `findmnt /` shows the root filesystem on `/dev/nvme0n1p2` (or the NVMe `PARTUUID`).
- `/boot/cmdline.txt` and `/etc/fstab` reference the NVMe `PARTUUID` values emitted by `sudo blkid /dev/nvme0n1p1 /dev/nvme0n1p2`.
- `sudo vclog -m tip` (or `sudo vcgencmd bootloader_config`) reports the expected `BOOT_ORDER=0xf461` without bootloader warnings.

A freshly built image ships with `first-boot-prepare.service`, ensuring `rpi-clone`,
`rpi-eeprom`, `vcgencmd`, `ethtool`, `jq`, `parted`, `lsblk`, `wipefs`, and `just` are
ready before you run these commands.
