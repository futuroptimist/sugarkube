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

> **Before you start**
>
> - If `sudo scripts/boot_order.sh print` (or `sudo just boot-order print`) already shows
>   `BOOT_ORDER=0xf461`, you can skip the boot-order step below.
> - If `lsblk` shows `/dev/nvme0n1` (or your target drive) already carrying the `boot`
>   and `root` partitions, the disk has been initialized. Skip the cloning step and jump to
>   verification.

1. **Align the EEPROM boot order (SD → NVMe → USB).**
   ```bash
   sudo just boot-order sd-nvme-usb
   ```
   This keeps the SD card as the first target so you can recover easily, while still
   preferring NVMe on subsequent retries.
2. **Clone the SD card onto NVMe.**
   ```bash
   sudo just clone-ssd TARGET=/dev/nvme0n1
   ```
   Under the hood this runs `rpi-clone -f -U /dev/nvme0n1`. The `-U` flag performs the
   one-time filesystem setup, so keep it for the initial clone. Re-runs without `-U` only
   update files.
3. **Optionally run the end-to-end helper.** If you prefer a guided flow that performs the
   spot check, boot-order alignment (unless `SKIP_EEPROM=1`), clone, and reboot, use:
   ```bash
   sudo just migrate-to-nvme
   ```
4. **Verify the next boot.**
   ```bash
   sudo just post-clone-verify
   ```

> **Troubleshooting**
>
> Mount the clone output (`sudo mount /dev/nvme0n1p1 /mnt/clone` and
> `sudo mount /dev/nvme0n1p2 /mnt/clone/root`) to inspect `/mnt/clone/cmdline.txt` and
> `/mnt/clone/root/etc/fstab`. Confirm the `root=` entry and `PARTUUID` values match your
> NVMe device.

To force a single SD boot while leaving the NVMe attached, set a one-time override before
rebooting:

```bash
sudo rpi-eeprom-config --apply <(printf 'set_reboot_order=0xf1\n')
```

The override applies to the next reboot only.

**Verification checklist**

- The Pi boots from NVMe (check `lsblk` or the login banner for `/dev/nvme0n1`).
- `sudo blkid` shows the active `root` `PARTUUID` values pointing to the NVMe drive.
- `sudo vclog -m tip` reports recent firmware logs without errors.

A freshly built image ships with `first-boot-prepare.service`, ensuring `rpi-clone`,
`rpi-eeprom`, `vcgencmd`, `ethtool`, `jq`, `parted`, `lsblk`, `wipefs`, and `just` are
ready before you run these commands.
