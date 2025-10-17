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
> - `sudo just boot-order print` → If the output already shows `BOOT_ORDER=0xf461`, skip the Boot-Order step.
> - `lsblk -e7 -o NAME,TYPE,SIZE,MOUNTPOINTS` → If `/dev/nvme0n1` already has `boot` and `root` partitions, skip initialization and jump to the verification checklist.

### 1. Align the EEPROM boot order (optional)

Prefer SD → NVMe → USB → repeat so recovery media in the SD slot always wins:

```bash
sudo just boot-order sd-nvme-usb
```

Need to surface the current configuration again? Run `sudo just boot-order print`. Adapters that require `PCIE_PROBE=1` can opt in per run:

```bash
sudo PCIE_PROBE=1 just boot-order nvme-first
```

### 2. Clone the SD card to NVMe

`just clone-ssd` still wraps the process, but the resilient one-liner below works even on a blank drive. The `-U` flag initializes boot and root partitions on first use; omit it on subsequent refreshes if you want to preserve existing UUIDs.

```bash
sudo rpi-clone -f -U /dev/nvme0n1
```

When you prefer the guided workflow, run `sudo just clone-ssd TARGET=/dev/nvme0n1 WIPE=1` and follow the prompts.

### 3. Optional fast path

To chain the spot check, boot-order, clone, and reboot steps automatically:

```bash
sudo just migrate-to-nvme
```

> **Troubleshooting**
> ```bash
> sudo mkdir -p /mnt/clone
> sudo mount /dev/nvme0n1p1 /mnt/clone
> sudo mount /dev/nvme0n1p2 /mnt/clone/root
> ls /mnt/clone        # cmdline.txt lives here
> ls /mnt/clone/root   # check etc/fstab
> ```
> Unmount with `sudo umount /mnt/clone/root /mnt/clone` when finished.

### One-time SD override

Need to test a fresh SD card without unplugging the NVMe enclosure? Apply a one-shot override—the next boot will prefer SD, then the EEPROM reverts to its persistent order:

```bash
tmp=$(mktemp)
printf 'set_reboot_order=0xf1\n' | sudo tee "$tmp" >/dev/null
sudo rpi-eeprom-config --edit "$tmp"
rm "$tmp"
```

### Verification checklist

- Booted from NVMe (`lsblk -e7 -o NAME,MOUNTPOINTS` shows `/boot/firmware` and `/` on `/dev/nvme0n1p1/2`).
- `sudo rpi-eeprom-config | grep -F BOOT_ORDER` reports the intended preset and PARTUUIDs in `/etc/fstab` match the NVMe partitions.
- `sudo vclog -m tip` (or `sudo vcgencmd bootloader_config`) is free of bootloader warnings.

A freshly built image ships with `first-boot-prepare.service`, ensuring `rpi-clone`,
`rpi-eeprom`, `vcgencmd`, `ethtool`, `jq`, `parted`, `lsblk`, `wipefs`, and `just` are
ready before you run these commands.
