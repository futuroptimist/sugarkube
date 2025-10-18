# NVMe Health Monitoring and Alerting for Raspberry Pi + NVMe Boot

## Overview
Monitoring Non-Volatile Memory Express (NVMe) Self-Monitoring, Analysis, and Reporting
Technology (SMART) data exposes drive health indicators before faults become user-visible.
Raspberry Pi systems that boot from NVMe benefit from proactive wear tracking because the boot
device often hosts both the operating system and cluster workloads. Keeping an eye on wear
trends ensures that maintenance can be scheduled before an outage.

## Key Metrics
- **Percentage Used** – Reports remaining endurance margin. Values above 80% suggest that the
  drive is nearing end-of-life.
- **Data Units Written (DUW)** – Counts 512,000-byte units written to NAND. Convert to terabytes
  written (TBW) using `DUW * 512000 / 1e12`.
- **Critical Warning** – Non-zero values indicate thermal throttling, spare depletion, or device
  reliability issues. Treat any `1` bit as actionable.
- **Media Errors** – Number of unrecoverable NAND errors. Any value above `0` warrants
  investigation.
- **Unsafe Shutdowns** – Power-loss events without a clean shutdown. High counts imply power
  stability problems.

## Manual Checks
Run one-shot inspections with `nvme-cli` and `smartctl`:

```bash
sudo nvme smart-log /dev/nvme0n1
sudo nvme smart-log /dev/nvme0n1 | \
  egrep 'critical_warning|percentage_used|data_units_written|media_errors|num_err_log_entries'
sudo smartctl -a /dev/nvme0
```

Convert Data Units Written to terabytes in Python:

```python
#!/usr/bin/env python3
units = int(input("Enter data_units_written: "))
tbw = units * 512_000 / 1e12
print(f"{tbw:.2f} TB written")
```

## Automation
Add the following script as `nvme-health-check.sh` to gather SMART metrics, convert DUW to TB,
compare against thresholds, and emit syslog alerts. The script exits non-zero when thresholds
are exceeded so cron or systemd can notify operators.

```bash
#!/usr/bin/env bash
set -euo pipefail

DEVICE="${NVME_DEVICE:-/dev/nvme0n1}"
PCT_THRESH="${NVME_PCT_THRESH:-80}"
TBW_LIMIT="${NVME_TBW_LIMIT_TB:-300}"
MEDIA_ERR_THRESH="${NVME_MEDIA_ERR_THRESH:-0}"
UNSAFE_SHUT_THRESH="${NVME_UNSAFE_SHUT_THRESH:-5}"
LOGGER_TAG="nvme-health"

log() {
  logger -t "$LOGGER_TAG" "$1"
}

smart_json=$(nvme smart-log "$DEVICE" | tr -d '\r')
get_field() {
  echo "$smart_json" | awk -F ':' -v key="$1" '$1 ~ key { gsub(/ /, "", $2); print $2 }'
}

critical_warning=$(get_field "critical_warning")
percentage_used=$(get_field "percentage_used")
data_units_written=$(get_field "data_units_written")
media_errors=$(get_field "media_errors")
unsafe_shutdowns=$(get_field "unsafe_shutdowns")

# Convert DUW (512,000-byte units) to terabytes.
tbw=$(awk -v duw="$data_units_written" 'BEGIN { printf "%.2f", duw * 512000 / 1e12 }')

status=0
message="NVMe health check: pct=${percentage_used}%"
message+="; tbw=${tbw}TB, warnings=${critical_warning}"
message+="; media=${media_errors}, unsafe=${unsafe_shutdowns}"

if [[ "$critical_warning" != "0x00" ]]; then
  log "CRITICAL warning flag set: $critical_warning"
  status=1
fi

if (( percentage_used >= PCT_THRESH )); then
  log "Wear level ${percentage_used}% exceeds threshold ${PCT_THRESH}%"
  status=1
fi

if (( $(echo "$tbw >= $TBW_LIMIT" | bc -l) )); then
  log "Total bytes written ${tbw}TB exceeds ${TBW_LIMIT}TB"
  status=1
fi

if (( media_errors > MEDIA_ERR_THRESH )); then
  log "Media errors ${media_errors} exceed ${MEDIA_ERR_THRESH}"
  status=1
fi

if (( unsafe_shutdowns > UNSAFE_SHUT_THRESH )); then
  log "Unsafe shutdowns ${unsafe_shutdowns} exceed ${UNSAFE_SHUT_THRESH}"
  status=1
fi

log "$message"
exit $status
```

## Deployment
1. Install dependencies:
   ```bash
   sudo apt update && sudo apt install -y nvme-cli smartmontools bc
   ```
2. Save the script, then make it executable:
   ```bash
   sudo install -m 0755 nvme-health-check.sh /usr/local/sbin/
   ```
3. Add a root cron job to run every six hours:
   ```bash
   sudo crontab -e
   # Add: 0 */6 * * * /usr/local/sbin/nvme-health-check.sh
   ```
4. Optional systemd timer (create under `/etc/systemd/system/`):
   - `nvme-health-check.service`:
     ```ini
     [Unit]
     Description=NVMe SMART health check

     [Service]
     Type=oneshot
     ExecStart=/usr/local/sbin/nvme-health-check.sh
     ```
   - `nvme-health-check.timer`:
     ```ini
     [Unit]
     Description=Run NVMe SMART health check every 6 hours

     [Timer]
     OnBootSec=5m
     OnUnitActiveSec=6h

     [Install]
     WantedBy=timers.target
     ```
   Enable with:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now nvme-health-check.timer
   ```

## Raspberry Pi Notes
- Maintain a stable 5V power supply capable of delivering peak current to both the Pi and the
  NVMe HAT. Brownouts correlate with unsafe shutdown counts.
- Ensure adequate cooling for the Pi and the NVMe enclosure to avoid thermal throttling.
- Forward syslog entries to Prometheus, Loki, or a central syslog server for fleet monitoring.
- Keep a pre-imaged spare NVMe drive so replacement is a quick swap when wear thresholds are met.

## Future Enhancements
- Export SMART metrics as JSON (for example, via `nvme smart-log --json`) so a k3s scraper can
  publish them as Prometheus metrics.
- Integrate the workflow with `just nvme-health` for ad-hoc checks and `just nvme-alerts` for
  alerting pipelines in the sugarkube toolkit.
