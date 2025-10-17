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

1. Optional: update EEPROM + boot order for NVMe adapters.
   ```bash
   sudo just eeprom-nvme-first
   ```
2. Clone the SD card to the first non-SD disk (prefers `/dev/nvme0n1`).
   ```bash
   sudo just clone-ssd
   ```
3. Run the happy-path migration, which chains the above, reboots, and leaves a log in
   `artifacts/migrate-to-nvme/`. **If you already ran steps 1 and 2 successfully, skip this step.**
   ```bash
   sudo just migrate-to-nvme
   ```
4. After the reboot, confirm the Pi is running from NVMe.
   ```bash
   sudo just post-clone-verify
   ```

A freshly built image ships with `first-boot-prepare.service`, ensuring `rpi-clone`,
`rpi-eeprom`, `vcgencmd`, `ethtool`, `jq`, `parted`, `lsblk`, `wipefs`, and `just` are
ready before you run these commands.
