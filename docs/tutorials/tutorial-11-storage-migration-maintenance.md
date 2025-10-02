# Tutorial 11: Storage Migration and Long-Term Maintenance

## Overview
This chapter of the [Sugarkube Tutorial Roadmap](./index.md#tutorial-11-storage-migration-and-long-term-maintenance)
teaches you how to move a Sugarkube deployment from SD media to a resilient SSD, validate the clone,
and put day-two maintenance on autopilot—even when the enclosure lives outdoors on solar power. You
will practice running `scripts/ssd_clone.py`, reviewing its reports, capturing SMART health metrics,
logging solar charge status, and scheduling recurring backups so nothing is left to guesswork.

By the end you will have:
* Captured a full clone plan, execution log, and validation checklist you can reuse for future
  migrations.
* Recorded drive health metrics (SMART, wear-level, filesystem capacity) before and after the clone to
  spot drift early.
* Implemented a rotating backup routine and monthly maintenance runbook tailored to your Sugarkube,
  including solar and weather-proofing checkpoints.

## Prerequisites
* Completed artefacts from [Tutorial 1](./tutorial-01-computing-foundations.md) through
  [Tutorial 10](./tutorial-10-first-boot-verification-self-healing.md), including the validated Pi,
  first-boot reports, and SSH access.
* A target SSD or NVMe drive larger than your SD card, plus the USB/SATA bridge recommended in
  [Tutorial 6](./tutorial-06-raspberry-pi-hardware-power.md) and access to the solar charge
  controller harness so you can monitor power during cloning.
* Your workstation with the Sugarkube repository cloned and `ssh`, `scp`, and `jq` installed.
* Optional: a powered USB hub and ESD-safe mat to keep the Pi stable while swapping media.

> [!WARNING]
> Confirm the SSD is empty or that its data is already backed up. The clone helper overwrites the
> target disk completely. Double-check device paths before you press Enter.

## Lab: Clone, Validate, and Automate Maintenance
Create a new evidence workspace at `~/sugarkube-labs/tutorial-11/`. Store all logs, screenshots, and
notes so reviewers can audit your run.

### 1. Prepare the workspace and capture baseline metrics
1. On your workstation, create folders and capture the current state of the Pi storage:

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-11/{notes,logs,media,reports,backups}
   cd ~/sugarkube-labs/tutorial-11

   cat <<'MARKDOWN' > notes/README.md
   # Tutorial 11 Lab Journal
   - Date:
   - Pi hostname/IP:
   - Source media size:
   - Target SSD model/serial:
   MARKDOWN
   ```

2. Record Pi storage details before attaching the SSD:

   ```bash
   ssh pi@192.0.2.10 'sudo lsblk -o NAME,SIZE,TYPE,MOUNTPOINT' \
     | tee logs/pre-clone-lsblk.txt
   ssh pi@192.0.2.10 'sudo df -hT' | tee logs/pre-clone-df.txt
   ```

3. Collect SMART data for the SD card (if supported) and note the absence if not:

   ```bash
   ssh pi@192.0.2.10 'sudo smartctl -a /dev/mmcblk0 || echo "SMART unsupported"' \
     | tee logs/pre-clone-smart.txt
   ```

4. Note the solar charge controller state before cloning so you can spot anomalies during the long
   copy operation. If the controller exposes logs, capture them:

   ```bash
   ssh pi@192.0.2.10 'sudo tail -n 50 /var/log/sugarkube/charge-controller.log' \
     | tee logs/pre-clone-charge-controller.txt
   ```

   Otherwise photograph the display and place the image under `media/` with annotated voltage and
   wattage.

> [!TIP]
> Photograph or screenshot the cabling layout before proceeding. Save the image under `media/` so you
> can reproduce the setup or share it with teammates.

### 2. Connect the SSD and map device paths
1. Power down the Pi gracefully:

   ```bash
   ssh pi@192.0.2.10 'sudo shutdown -h now'
   ```

2. Once LEDs stop blinking, connect the SSD via your USB bridge. Ensure the drive receives power and
   is firmly seated.

> [!TIP]
> If the Pi is running solely on solar, either perform the clone during daylight with ample battery
> reserve or temporarily connect grid power so the controller does not brown out mid-clone.

3. Boot the Pi and wait 60 seconds. Then capture the updated block device list:

   ```bash
   ssh pi@192.0.2.10 'sudo lsblk -o NAME,SIZE,MODEL,TYPE,MOUNTPOINT' \
     | tee logs/post-ssd-lsblk.txt
   ```

4. Update `notes/README.md` with the detected target device (for example `/dev/sda`). Highlight
   capacity differences so you can verify the clone occupies the full SSD.

> [!TROUBLESHOOT]
> If the SSD does not appear, reseat the USB bridge, try a different port, or insert a powered hub. If
> `dmesg` shows `usb 2-1: device descriptor read/64, error -71`, the bridge may need additional power
> or a shorter cable.

### 3. Dry-run the clone plan with `scripts/ssd_clone.py`
1. Copy the helper to the Pi (already installed under `/opt/sugarkube`, but we run from the repo so you
   can edit if needed):

   ```bash
   scp scripts/ssd_clone.py pi@192.0.2.10:/tmp/ssd_clone.py
   ssh pi@192.0.2.10 'chmod +x /tmp/ssd_clone.py'
   ```

2. Preview the plan without writing:

   ```bash
   ssh pi@192.0.2.10 \
     'sudo /tmp/ssd_clone.py --target /dev/sda --dry-run --log /var/log/sugarkube/ssd-clone.dry-run.log'
   ```

3. Retrieve the dry-run report for your archive:

   ```bash
   scp pi@192.0.2.10:/var/log/sugarkube/ssd-clone.dry-run.log logs/
   ```

4. Review the log for warnings or skipped steps. Document any questions or anomalies in
   `notes/README.md` before you proceed.

> [!NOTE]
> The helper stores resumable state in `/var/log/sugarkube/ssd_clone.state.json`. Keep the file until
> you finish validation so you can rerun with `--resume` if necessary.

### 4. Execute the SSD clone and verify completion
1. Run the clone for real (expect 20–60 minutes depending on media speed):

   ```bash
   ssh pi@192.0.2.10 \
     'sudo /tmp/ssd_clone.py --target /dev/sda --log /var/log/sugarkube/ssd-clone.run.log'
   ```

   Leave the SSH session open so you can see progress updates.

2. When the command prints `Clone completed`, confirm the done flag exists:

   ```bash
   ssh pi@192.0.2.10 'sudo ls -l /var/log/sugarkube/ssd-clone.done'
   ```

3. Pull the run log and state file for archival:

   ```bash
   scp pi@192.0.2.10:/var/log/sugarkube/ssd-clone.run.log logs/
   scp pi@192.0.2.10:/var/log/sugarkube/ssd_clone.state.json reports/
   ```

4. Capture a checksum inventory for the cloned partitions:

   ```bash
   ssh pi@192.0.2.10 'sudo /tmp/ssd_clone.py --target /dev/sda --verify-only' \
     | tee logs/post-clone-verify.txt
   ```

> [!WARNING]
> Do not disconnect the SSD until verification finishes. Interrupting USB storage while it is mounted
> or syncing can corrupt both disks.

### 5. Swap boot media and validate the SSD boot
1. Shut down the Pi:

   ```bash
   ssh pi@192.0.2.10 'sudo shutdown -h now'
   ```

2. Remove the SD card. Leave the SSD attached.

3. Power on the Pi and wait for network reachability. Reconnect via SSH using the same IP. Confirm the
   root filesystem now resides on the SSD:

   ```bash
   ssh pi@192.0.2.10 'mount | grep "on / "'
   ssh pi@192.0.2.10 'sudo lsblk -o NAME,SIZE,ROTA,MOUNTPOINT'
   ```

4. Regenerate the first-boot summary for the new storage baseline:

   ```bash
   ssh pi@192.0.2.10 \
     'sudo /opt/sugarkube/pi_node_verifier.sh --log /boot/first-boot-report/post-ssd-rerun.txt'
   scp -r pi@192.0.2.10:/boot/first-boot-report reports/post-ssd-report
   ```

5. Update `notes/README.md` with timestamps, serial numbers, and any deviations you noticed during the
   boot on SSD.

6. Tail the charge-controller log (or photograph the display again) to confirm the power system stayed
   stable while booting from SSD:

   ```bash
   ssh pi@192.0.2.10 'sudo tail -n 50 /var/log/sugarkube/charge-controller.log' \
     | tee logs/post-ssd-charge-controller.txt
   ```

> [!TIP]
> Take a second photo showing the Pi operating without the SD card. Include LED indicators to prove the
> SSD is active.

### 6. Collect post-clone health metrics
1. Gather SMART data from the SSD:

   ```bash
   ssh pi@192.0.2.10 'sudo smartctl -a /dev/sda' | tee logs/post-clone-smart.txt
   ```

2. Compare filesystem capacity and free space with the pre-clone snapshot:

   ```bash
   ssh pi@192.0.2.10 'sudo df -hT' | tee logs/post-clone-df.txt
   ```

3. Export the health monitor journal:

   ```bash
   ssh pi@192.0.2.10 'sudo journalctl -u ssd-clone.service --no-pager' \
     | tee logs/ssd-clone-service-journal.txt
   ```

4. Summarise findings in `notes/README.md`, noting any SMART attributes or solar voltage swings that
   warrant follow-up.

5. If daylight is available, record another snapshot of the charge-controller output to compare against
   the pre-clone state. Append the reading to `logs/post-clone-charge-controller.txt` or add a new photo
   to `media/`.

> [!TROUBLESHOOT]
> If SMART reports `Read SMART Data Failed`, install `sudo apt install smartmontools` on the Pi and rerun.
> Some USB bridges require the `-d sat` flag: `sudo smartctl -a -d sat /dev/sda`.

### 7. Configure recurring backups and maintenance reminders
1. Designate a backup destination mounted at `/mnt/sugarkube-backups`. Create a script that archives
   key directories and compresses the `/boot/first-boot-report` folder:

   ```bash
   cat <<'SCRIPT' > backups/backup-once.sh
   #!/usr/bin/env bash
   set -euo pipefail
   DEST="/mnt/sugarkube-backups/$(date +%Y-%m-%d)"
   sudo mkdir -p "$DEST"
   sudo rsync -aHAX --delete /etc/ "$DEST/etc/"
   sudo rsync -aHAX /var/log/sugarkube/ "$DEST/var-log-sugarkube/"
   sudo cp /var/log/sugarkube/charge-controller.log "$DEST/charge-controller.log"
   sudo tar -C /boot -czf "$DEST/first-boot-report.tgz" first-boot-report
   sudo journalctl --since "1 day ago" > "$DEST/system-journal.log"
   SCRIPT
   chmod +x backups/backup-once.sh
   scp backups/backup-once.sh pi@192.0.2.10:/tmp/backup-once.sh
   ssh pi@192.0.2.10 'chmod +x /tmp/backup-once.sh'
   ```

2. Execute the backup manually and review the output:

   ```bash
   ssh pi@192.0.2.10 'sudo /tmp/backup-once.sh' | tee logs/manual-backup.txt
   ```

3. Schedule a monthly maintenance job on the Pi to run the backup script, refresh SMART metrics, and
   note capacity:

   ```bash
   ssh pi@192.0.2.10 'cat <<"CRON" | sudo tee /etc/cron.d/sugarkube-maintenance
   # Sugarkube monthly maintenance
   0 2 1 * * root /tmp/backup-once.sh >> /var/log/sugarkube/maintenance.log 2>&1
   30 2 1 * * root smartctl -a /dev/sda > /var/log/sugarkube/smart-last.txt
   45 2 1 * * root df -hT > /var/log/sugarkube/df-last.txt
   50 2 1 * * root tail -n 200 /var/log/sugarkube/charge-controller.log > \
     /var/log/sugarkube/charge-controller-last.txt
   CRON'
   ```

4. Document where backups land and how to restore them. Include the mount point, rotation policy, and
   who reviews the logs in your lab journal.

> [!NOTE]
> If you prefer cloud backups, replace the `rsync` commands with `rclone` or `restic` invocations aimed
> at an S3 bucket. Ensure credentials are stored in `/etc/sugarkube/secrets.d/` with permissions `600`.

### 8. Build a monthly maintenance checklist
1. Draft a Markdown checklist that peers can follow when reviewing maintenance evidence:

   ```bash
   cat <<'MARKDOWN' > notes/monthly-maintenance-checklist.md
   # Sugarkube Monthly Maintenance
   - [ ] Confirm /var/log/sugarkube/maintenance.log exists and contains the latest run.
   - [ ] Review /var/log/sugarkube/smart-last.txt for increasing reallocated sectors.
   - [ ] Confirm backup directory on /mnt/sugarkube-backups has current timestamp.
   - [ ] Spot-check df-last.txt for >20% free space on root and data partitions.
   - [ ] Test restore procedure on a spare Pi or loopback mount once per quarter.
   MARKDOWN
   ```

2. Sync the checklist back to your workstation records:

   ```bash
   scp pi@192.0.2.10:/var/log/sugarkube/{maintenance.log,smart-last.txt,df-last.txt} logs/ || true
   ```

3. Update `notes/README.md` with lessons learned, gaps you still need to address, and links to any
   automation you plan to upstream.

> [!TIP]
> Store the maintenance checklist in your team wiki or issue tracker so multiple caretakers can share
> the workload. Automated reminders (calendar events or GitHub issues) keep the cadence reliable.

## Milestone Checklist
Use this list to confirm you met every objective before moving on:

- [ ] Recorded pre- and post-clone storage metrics (`lsblk`, `df`, SMART) in your evidence workspace.
- [ ] Completed an SSD clone using `scripts/ssd_clone.py` and archived the dry-run, run, and verify logs.
- [ ] Booted from the SSD and captured a refreshed `/boot/first-boot-report` bundle.
- [ ] Implemented a backup script, ran it once manually, and scheduled recurring maintenance tasks.
- [ ] Authored a monthly maintenance checklist and synced supporting logs to your lab notebook.

## Next Steps
Continue to [Tutorial 12: Contributing New Features and Automation](./tutorial-12-contributing-new-features-automation.md)
to learn how to propose improvements, extend automation, and collaborate on future Sugarkube
releases.

> [!NOTE]
> Automated coverage in `tests/test_tutorial_11_12_next_steps.py` keeps this section pointing to the
> published Tutorial 12 guide, and `tests/test_tutorial_next_steps_links.py` ensures the link resolves.
