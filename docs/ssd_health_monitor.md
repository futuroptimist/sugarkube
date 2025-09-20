# SSD Health Monitor

The Sugarkube image now ships with an optional SSD/NVMe health monitor that wraps
[`smartctl`](https://manpages.debian.org/smartmontools/smartctl.8.en.html) so operators can
capture wear, temperature, and SMART results after migrating to solid-state storage.
The helper stores JSON and Markdown reports under `~/sugarkube/reports/ssd-health/` so the
history survives across reboots and can be exported when filing support requests.

## Requirements

- Raspberry Pi running the Sugarkube image with the SSD or NVMe device attached.
- `smartmontools` installed. Pi images generated from this repository already include it. If
  you're running on a downstream system, install it manually:

  ```bash
  sudo apt update
  sudo apt install -y smartmontools
  ```

- Root access. `smartctl` requires elevated privileges to query device telemetry.

## Run a One-Off Health Capture

Invoke the helper with `sudo` so it can talk to the storage controller. By default it discovers
the root filesystem device and writes reports to `~/sugarkube/reports/ssd-health/`:

```bash
sudo ./scripts/ssd_health_monitor.py
```

You can target a specific device (for example if the SSD is attached but not yet booted from):

```bash
sudo ./scripts/ssd_health_monitor.py --device /dev/sda
```

The script prints a short summary to stdout, then writes detailed JSON/Markdown snapshots you can
reference later. Set `--print-json` to also stream the JSON payload to the terminal or pass
`--no-markdown`/`--no-json` to disable individual outputs.

## Thresholds & Exit Codes

The monitor applies two guardrails out of the box:

- Warn when drive wear reaches 80% consumed life (`--warn-percentage`).
- Warn when temperature reaches 70 °C (`--warn-temperature`).

If the SMART controller reports an overall failure the warning list includes it automatically.
Combine `--fail-on-warn` with a systemd unit (see below) to fail CI/CD or health checks when the
wear/temperature threshold trips.

## Automate With systemd

Create a service and timer so the monitor captures telemetry daily. These units live in
`/etc/systemd/system/` and can be dropped in via `sudo tee`:

```bash
sudo tee /etc/systemd/system/sugarkube-ssd-health.service <<'SERVICE'
[Unit]
Description=Collect SSD SMART metrics for Sugarkube
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/sugarkube-ssd-health.sh
SERVICE

sudo tee /usr/local/bin/sugarkube-ssd-health.sh <<'SCRIPT'
#!/bin/bash
set -euo pipefail
/usr/local/bin/python3 /opt/sugarkube/scripts/ssd_health_monitor.py --fail-on-warn --print-json
SCRIPT
sudo chmod +x /usr/local/bin/sugarkube-ssd-health.sh

sudo tee /etc/systemd/system/sugarkube-ssd-health.timer <<'TIMER'
[Unit]
Description=Schedule Sugarkube SSD SMART collection

[Timer]
OnCalendar=daily
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
TIMER

sudo systemctl daemon-reload
sudo systemctl enable --now sugarkube-ssd-health.timer
```

Adjust the script path if you install Sugarkube somewhere other than `/opt/sugarkube`. The timer
runs once per day and records telemetry in the standard report directory so trends are easy to
spot.

## Make & just Integration

To run the helper without remembering the full path, use the new shortcuts:

```bash
sudo make monitor-ssd-health
# or
sudo just monitor-ssd-health
```

Pass custom flags via `MONITOR_ARGS`:

```bash
sudo MONITOR_ARGS='--warn-percentage 70 --print-json' make monitor-ssd-health
```

These wrappers make it easy to integrate the monitor into your own automation or recovery
playbooks.

## Troubleshooting

- **`smartctl` missing:** install the `smartmontools` package or run the monitor on a Sugarkube
  image built after this change.
- **`Unable to determine the block device`**: specify the device manually with `--device`. USB
  adapters that expose multiple logical units sometimes confuse the auto-detection.
- **Warnings about wear/temperature:** inspect the generated JSON to confirm the reading, then
  plan a replacement SSD or improve airflow.
