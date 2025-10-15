# Raspberry Pi 5 image spot check

This guide captures the Pi 5 + Bookworm verification flow that now ships with the
`sugarkube` image. The checks are scripted so you can copy/paste a single command,
review the ✅/⚠️/❌ summary, and move straight into NVMe cloning when the baseline looks
healthy.

## TL;DR: run the automated check

```bash
cd /opt/sugarkube  # or the path where the repo lives
just spot-check
```

* Output is mirrored under `artifacts/spot-check/`:
  * `summary.md` – one-line status per check.
  * `summary.json` – machine-readable details.
  * `spot-check.log` – full command transcript (`df -h`, `lsblk`, `journalctl`, etc.).
* The command exits non-zero if any required check fails.

Typical success output:

```
✅ system: Bookworm aarch64 kernel 6.12.0+rpt
✅ time: NTP synced (timezone America/Los_Angeles)
✅ storage: /boot/firmware=XXXXXXXX / = YYYYYYYY
✅ ping-lan: lan latency avg 0.53 ms
✅ ping-wan: wan latency avg 17.3 ms
⚠️ link: eth0 100Mb/s   # Warning only if link < 1000Mb/s
✅ temp: Idle temp 43.1°C
✅ memory: Available memory 7564 MiB
✅ throttle: No throttling detected
⚠️ logs: Review journal priority 3 entries   # only if errors beyond known Bluetooth/bgscan noise
```

If a required check fails the script prints `❌ …` and exits with code `1`. Optional
warnings (`⚠️`) document suboptimal conditions without stopping the workflow.

## What each check covers

| Check key | Pass criteria | Failure notes |
| --- | --- | --- |
| `system` | `VERSION_CODENAME=bookworm`, `uname -m=aarch64`, kernel ≥ 6.12 | Ensure the right OS image was flashed. |
| `time` | `timedatectl` reports `NTPSynchronized=yes` and a timezone | Run `sudo raspi-config nonint do_change_timezone …` if unset. |
| `storage` | `/dev/mmcblk0p1` → `/boot/firmware`, `/dev/mmcblk0p2` → `/` | Re-flash or repair partitions if mounts or UUIDs differ. |
| `ping-lan` | 0% loss to the default gateway (avg latency recorded) | Verify cabling or DHCP. |
| `ping-wan` | 0% loss to `1.1.1.1` | Confirms outbound reachability (DNS optional). |
| `link` | eth0 speed ≥ `1000Mb/s` | Warning only; some switches negotiate 100Mb/s. |
| `services` | No `flywheel`, `k3s`, `cloudflared`, `containerd` units enabled | Disable stray services before imaging. |
| `logs` | `journalctl -b -p 3` only shows benign Bluetooth `vcp/mcp/bap` or `wpa_supplicant bgscan simple` warnings | Unexpected errors stay in the log and raise ⚠️. |
| `temp` | `vcgencmd measure_temp` < 60 °C at idle | Suggest using the official 27 W PSU and adequate cooling if high. |
| `memory` | `free -h` reports > 7 GiB `available` (8 GB model) | Warning only on smaller SKUs. |
| `throttle` | `vcgencmd get_throttled` returns `0x0` | Non-zero indicates power or thermal throttling; check PSU. |
| `repos` | Optional check for `/home/*/{sugarkube,dspace,token.place}` | Flags missing repos when the image profile expects them. |

## Known benign log noise

`journalctl -b -p 3` can include the following lines even on healthy systems:

* `bluetoothd[...]: Failed to set power to on: org.bluez.Error.Failed`
* `bluetoothd[...]: sap-server: Operation not permitted`
* `wpa_supplicant[...] bgscan simple: Failed to enable signal monitoring`

The spot check filters these so they do not raise a failure. Anything else at priority 3
or higher will surface as a ⚠️ for manual review.

## Thresholds & tips

* Kernel 6.12 or newer is required for stable Pi 5 PCIe/NVMe support.
* Keep idle temperatures under 60 °C; the official 27 W USB-C PSU avoids brown-outs.
* Gigabit Ethernet ensures NVMe imaging finishes quickly; sub-1 Gb/s links trigger a warning only.
* `WIPE=1` can be exported before cloning to wipe residual partition signatures on the target NVMe.

## Next steps: clone to NVMe

When the spot check exits successfully you can run the full "happy path":

```bash
just migrate-to-nvme            # Spot check → EEPROM NVMe boot → clone → reboot
```

Flags for special cases:

* `SKIP_EEPROM=1` – skip the EEPROM update if you have already applied it.
* `WIPE=1` – wipe the NVMe disk before cloning.
* `NO_REBOOT=1` – perform the clone but stay on the current boot until you are ready.

After the reboot, confirm the new root is active:

```bash
just post-clone-verify
# ✅ Root filesystem on /dev/nvme0n1p2
# ✅ Boot firmware on /dev/nvme0n1p1
```

If either path reports `❌`, rerun `just clone-ssd TARGET=/dev/nvme0n1 WIPE=1` to repair the
clone before rebooting again.
