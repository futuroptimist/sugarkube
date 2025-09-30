---
personas:
  - hardware
  - software
---

# SSD Health Monitor

The sugarkube image now ships an opt-in helper that wraps `smartctl` to record SSD health metrics,
wear indicators, and temperatures. The script auto-detects the root disk, captures SMART payloads,
and writes Markdown/JSON reports to `~/sugarkube/reports/ssd-health/<timestamp>/` so operators can
spot failing drives before they corrupt k3s state.

## Requirements

Install `smartmontools` on the Pi (or any workstation that has the SSD attached):

```bash
sudo apt-get update
sudo apt-get install smartmontools
```

Run the helper with `sudo` so `smartctl` can read device information. When the tool is missing or the
platform does not expose SMART data, the helper returns warnings instead of silently succeeding.

## Run once

Execute the monitor after an SSD clone or whenever you want a snapshot of wear levels:

```bash
sudo ./scripts/ssd_health_monitor.py
```

The console output summarises each check:

- SMART overall health status (pass/fail/unavailable).
- Temperature compared to the default warn threshold (70 °C).
- Wear indicators (NVMe `percentage_used`, SATA `Percent_Lifetime_Remain`, spare blocks, etc.)
  compared to configurable warn/fail thresholds.

Every run stores:

- `report.md` — Markdown summary for quick sharing.
- `summary.json` — Structured status (omit with `--skip-json`).
- `smartctl.json` — Raw SMART payload (if available).

Override destinations or tweak thresholds as needed:

```bash
sudo ./scripts/ssd_health_monitor.py \
  --report-dir /var/log/sugarkube/reports \
  --tag weekly \
  --warn-temperature 65 \
  --warn-percentage-used 70 \
  --fail-percentage-used 90
```

Use `--device /dev/sdX` (or `/dev/nvme0n1`) to target disks that are not mounted as `/`. The helper
resolves partitions back to their parent device before invoking `smartctl`.

## Make/just integrations

New shortcuts mirror the Python helper so teams can reuse existing automation pipelines:

```bash
sudo make monitor-ssd-health HEALTH_ARGS="--tag post-clone"
```

```bash
sudo just monitor-ssd-health HEALTH_ARGS="--warn-temperature 65"
```

Set `HEALTH_CMD` to point at a different wrapper (for example, when running inside a container) while
keeping existing orchestration.

## Schedule periodic reports (optional)

Attach the monitor to a systemd timer to capture long-term trends. Drop the unit files under
`/etc/systemd/system/` and enable the timer:

`/etc/systemd/system/sugarkube-ssd-health.service`

```ini
[Unit]
Description=Run sugarkube SSD health monitor

[Service]
Type=oneshot
ExecStart=/usr/bin/sudo -n /opt/sugarkube/scripts/ssd_health_monitor.py --tag timer
WorkingDirectory=/opt/sugarkube
```

`/etc/systemd/system/sugarkube-ssd-health.timer`

```ini
[Unit]
Description=Daily SSD SMART sampling

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start the timer after copying the files:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sugarkube-ssd-health.timer
```

Reports continue to aggregate in `~/sugarkube/reports/ssd-health/`, tagged with the timer label so
operators can compare runs over time.
