# ✅ Raspberry Pi 5 Spot Check (Bookworm + NVMe Ready)

This guide exercises the automated `spot_check.sh` helper and explains how to
interpret the results on a Raspberry Pi 5 running Raspberry Pi OS Bookworm.
Use it immediately after flashing an SD card so the image is ready for SSD/NVMe
migration and k3s bootstrapping.

---

## 1. Run the automated spot check

```bash
cd /opt/sugarkube
just spot-check
```

The script prints emoji-labelled results and writes detailed artifacts to
`./artifacts/spot-check/`:

| File | Purpose |
| --- | --- |
| `summary.md` | Human-readable table with ✅/⚠️/❌ statuses. |
| `summary.json` | Machine-readable data for automations. |
| `spot-check.log` | Full command output captured during the run. |

The task exits **non-zero** if any required check fails so CI hooks can halt
immediately.

---

## 2. Expected results

### System baseline
- `uname -a` → Kernel `6.12.x` (or newer) with `aarch64` architecture.
- `/etc/os-release` → `VERSION_CODENAME=bookworm`.
- `hostname` matches your inventory label.

### Time & locale
- `timedatectl` should report `NTP service: active` (or `System clock synchronized: yes`).
- `Time zone:` must show your target region (e.g., `America/Los_Angeles`).
- `locale` should expose `LANG=en_US.UTF-8` (adjust if you seed a different locale).

### Storage layout
- `/dev/mmcblk0p1` mounted at `/boot/firmware` (Bookworm boot layout).
- `/dev/mmcblk0p2` mounted at `/`.
- UUIDs recorded in the JSON table for `/boot/firmware` and `/`.

### Networking and link speed
- `ping` to the default gateway and `1.1.1.1` → `0% packet loss`.
- `ethtool eth0` → `Speed: 1000Mb/s` when connected to gigabit Ethernet.
  - Lower speeds trigger ⚠️ but do not fail the check.

### Services & logs
- `systemctl` should **not** report `flywheel`, `k3s`, `cloudflared`, or `containerd` services.
- `journalctl -b -p 3` must be empty aside from known benign messages:
  - Bluetooth plugin initialization warnings (`bluetoothd`, `vcp`, `mcp`, `bap`).
  - `wpa_supplicant: bgscan simple` warnings.
  These are filtered automatically so unexpected errors surface as ❌.

### Health snapshot
- `vcgencmd measure_temp` < **60 °C** at idle.
- `free --bytes` shows **> 7 GiB** available on the 8 GB Pi 5 model.
- `vcgencmd get_throttled` returns `0x0`. Non-zero throttling raises ⚠️ with a
  reminder to use the official 27 W PSU.

### Optional repository sync
If your profile preloads supporting repos, expect to find `~/sugarkube`,
`~/dspace`, and `~/token.place`. Missing repos surface as ⚠️ only.

---

## 3. Troubleshooting failures

| Check | Common failure | Fix |
| --- | --- | --- |
| Time & locale | NTP inactive | `sudo timedatectl set-ntp true` then rerun the spot check. |
| Storage layout | `/boot/firmware` missing | Confirm the image booted from SD; reflash if partitions look corrupted. |
| Networking | WAN ping loss | Check cabling, switch, or DHCP configuration before proceeding. |
| Health | Memory < 7 GiB | Close background workloads or power-cycle to clear cgroups; persistent low memory suggests a bad image. |
| Services & logs | Unexpected systemd services | Disable the unit before cloning so the SSD starts from a clean baseline. |

Re-run `just spot-check` after applying fixes. The task is idempotent and
overwrites previous artifacts.

---

## 4. Next steps: clone to NVMe

Once the spot check is ✅ across required rows, migrate to NVMe with the
one-command happy path:

```bash
cd /opt/sugarkube
sudo just migrate-to-nvme
```

This pipeline:
1. Re-runs the spot check for a fresh baseline.
2. Updates EEPROM for NVMe-first boot (skip via `SKIP_EEPROM=1`).
3. Clones to the first non-SD disk (prefers `/dev/nvme0n1`) using the maintained
   `geerlingguy/rpi-clone` fork.
4. Reboots automatically unless `NO_REBOOT=1` is set.

After the reboot, confirm NVMe boot with:

```bash
just post-clone-verify
```

The verifier expects `/dev/nvme0n1p1` on `/boot/firmware` and `/dev/nvme0n1p2`
on `/`. It prints the active UUIDs so you can document the migration.

---

## 5. Logs and artifacts

- All spot check outputs live under `/opt/sugarkube/artifacts/spot-check/`.
- EEPROM updates write to `/opt/sugarkube/artifacts/eeprom/`.
- Cloning details are stored at `/opt/sugarkube/artifacts/clone-to-nvme/` plus
  `/var/log/first-boot-prepare.log` (captured on the very first boot).

Keep these files with your runbook or attach them to maintenance tickets; they
serve as the baseline proof before k3s enrollment.
