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
Sugarkube now ships `scripts/nvme_health_check.sh`, a Bash helper that gathers SMART metrics,
converts DUW to terabytes, and emits syslog-friendly messages. Configure thresholds via these
environment variables (or matching CLI flags):

- `NVME_DEVICE` (default: `/dev/nvme0n1`)
- `NVME_PCT_THRESH` (default: `80`)
- `NVME_TBW_LIMIT_TB` (default: `300`)
- `NVME_MEDIA_ERR_THRESH` (default: `0`)
- `NVME_UNSAFE_SHUT_THRESH` (default: `5`)
- `NVME_LOGGER_TAG` (default: `nvme-health`)
- `NVME_JSON_PATH` (default: unset) — write the raw `nvme smart-log --output-format=json`
  payload to the specified path for downstream scrapers.

Run the helper directly or through the unified CLI wrappers (for example,
`sugarkube nvme health` via the bundled Python entry point):

```bash
sudo ./scripts/nvme_health_check.sh
sudo sugarkube nvme health
sudo just nvme-health NVME_HEALTH_ARGS="--device /dev/nvme1n1"
task nvme:health NVME_HEALTH_ARGS="--dry-run"
sudo NVME_JSON_PATH=/var/log/sugarkube/nvme-smart.json ./scripts/nvme_health_check.sh
sudo sugarkube nvme health --json-path /var/log/sugarkube/nvme-smart.json
```

> **Tip:** `python -m sugarkube_toolkit nvme health --help` now lists the same
> device, threshold, logger, and JSON export flags as the underlying helper so
> you can discover supported options without leaving the CLI.

Regression coverage: `tests/test_sugarkube_toolkit_cli.py::test_nvme_health_invokes_helper`,
`tests/test_nvme_health_workflow.py`, and
`tests/nvme_health_check_test.py::test_nvme_health_writes_json_snapshot` keep the CLI, Make,
Just, and Task wrappers aligned with this guide. The error path is covered by
`tests/nvme_health_check_test.py::test_nvme_health_json_export_failure` so failed exports do
not go unnoticed.

## Telemetry integration

`scripts/nvme_health_check.sh` already exports raw SMART data when you pass
`--json-path`. Feed that output into `scripts/publish_telemetry.py` so the NVMe
metrics travel alongside verifier summaries and environment snapshots:

```bash
sudo ./scripts/nvme_health_check.sh --json-path /var/log/sugarkube/nvme-smart.json
python scripts/publish_telemetry.py \
  --nvme-json /var/log/sugarkube/nvme-smart.json \
  --markdown-dir docs/status/metrics \
  --dry-run
```

Set `SUGARKUBE_TELEMETRY_NVME_JSON` when you prefer an environment variable over
the explicit flag. Markdown snapshots now include an “NVMe Health” table that
highlights the critical warning bitfield, wear percentage, terabytes written,
media error count, and unsafe shutdown total. Regression coverage lives in
`tests/test_publish_telemetry.py::test_parse_nvme_smart_log_extracts_summary`,
`tests/test_publish_telemetry.py::test_main_includes_nvme_payload`, and
`tests/test_publish_telemetry.py::test_markdown_summary_includes_nvme_section` so
the telemetry enrichment stays aligned with this guide.

## Deployment
1. Install dependencies:
   ```bash
   sudo apt update && sudo apt install -y nvme-cli smartmontools bc
   ```
2. Install the shipped helper so cron/systemd can call it:
   ```bash
   sudo install -m 0755 scripts/nvme_health_check.sh /usr/local/sbin/nvme-health-check.sh
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
