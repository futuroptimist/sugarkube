# Raspberry Pi Image Spot Check (Pi 5 + Bookworm)

This guide replaces the ad-hoc checklist with a single command that captures logs,
JSON, and Markdown summaries. It targets Raspberry Pi 5 hardware running Raspberry
Pi OS Bookworm with `/boot/firmware`.

> **Happy path:** `just migrate-to-nvme` runs the spot check, ensures the EEPROM
> prefers NVMe, clones the SD card to NVMe, and reboots. See [Next steps](#next-steps-clone-to-nvme).

## Run the automated spot check

```bash
just spot-check
```

The helper wraps `scripts/spot_check.sh` and writes artifacts to
`artifacts/spot-check/`:

- `summary.json` – machine-readable check results
- `summary.md` – human-readable table
- `raw/` – command outputs for audits (`uname`, `timedatectl`, ping stats, etc.)

The command exits non-zero if any **required** check fails and prints a concise
summary in the terminal:

```
Raspberry Pi image spot check summary:
✅ System baseline — Raspberry Pi OS (Bookworm) kernel 6.12.x on aarch64 host pi5
✅ Time & locale — TZ=America/Los_Angeles NTP=yes LANG=en_US.UTF-8
✅ Storage layout — root=/dev/mmcblk0p2 boot=/dev/mmcblk0p1
✅ Networking — LAN loss=0% avg=0.25ms; WAN loss=0% avg=18.3ms
⚠️ Ethernet link — eth0 100Mb/s (warns if < 1000Mb/s or unknown)
✅ Services & logs — No unexpected services or errors
✅ Health — temp=43.5C throttle=0x0 mem_avail=7.3Gi
⚠️ Repo sync — Missing repos: token.place (warn only)
```

## Pass/fail criteria

| Check | Requirement |
| --- | --- |
| System baseline | `VERSION_CODENAME=bookworm`, `uname -m=aarch64`, kernel ≥ 6.12 |
| Time & locale | `timedatectl` reports `NTPSynchronized=yes`; timezone populated; `LANG` set |
| Storage | `/` on `/dev/mmcblk0p2`; `/boot/firmware` on `/dev/mmcblk0p1`; UUIDs captured |
| Networking | LAN + WAN pings complete with 0% loss (averages recorded in artifacts) |
| Ethernet link | Warns if `< 1000Mb/s` or unavailable (does not fail) |
| Services/logs | No running `flywheel`, `k3s`, `cloudflared`, `containerd`; no unexpected `journalctl -b -p3` errors |
| Health | `vcgencmd measure_temp` < 60 °C, `free --giga` > 7 Gi available on 8 GB models, `vcgencmd get_throttled=0x0` |
| Repo sync (optional) | Warns if `/home/pi/{sugarkube,dspace,token.place}` missing |

### Known benign log noise

The spot check tolerates these messages when scanning `journalctl -b -p 3`:

- Bluetooth `vcp/mcp/bap` plugin initialisation warnings
- `wpa_supplicant: bgscan simple` notices

Unexpected priority-3 errors remain a failure.

### Troubleshooting failures

| Symptom | Quick fix |
| --- | --- |
| Kernel < 6.12 | Update Raspberry Pi OS packages (`sudo apt full-upgrade`) and reboot |
| `vcgencmd get_throttled` ≠ `0x0` | Use the official 27 W USB-C PSU or reduce USB peripherals |
| WAN ping loss > 0% | Check ethernet cabling, VLAN tags, or upstream firewall |
| Repo warnings | Clone the missing repos under `/home/pi` if your image profile expects them |

## Next steps: clone to NVMe

When the spot check passes, you can migrate in one command:

```bash
sudo just migrate-to-nvme
```

The happy path performs:

1. `just spot-check`
2. `just eeprom-nvme-first` *(skip with `SKIP_EEPROM=1`)*
3. `just clone-ssd` *(autodetects `/dev/nvme0n1`; override with `TARGET=/dev/sdX`)*
4. Automatic reboot *(skip with `NO_REBOOT=1`)*

After the reboot, confirm the system runs entirely from NVMe:

```bash
just post-clone-verify  # expects / and /boot/firmware on /dev/nvme0n1p{2,1}
```

For clusters, prepare kernel knobs that k3s CNIs expect:

```bash
sudo just k3s-preflight
```

This loads `br_netfilter`, enables `net.ipv4.ip_forward=1`, and sets the bridge
nf iptables toggles without enabling k3s yet.
