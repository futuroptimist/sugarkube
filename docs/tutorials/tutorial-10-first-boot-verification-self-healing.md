# Tutorial 10: First Boot, Verification, and Self-Healing

## Overview
This guide continues the
[Sugarkube Tutorial Roadmap](./index.md#tutorial-10-first-boot-verification-and-self-healing)
by showing you how to take the freshly flashed media from Tutorial 9, perform a safe first boot,
collect the automatically generated health reports, and rehearse the self-healing workflows.
You will learn how `first_boot_service.py`, the bundled verifier, and supporting systemd units
collaborate to prove the cluster is ready for use.

By the end you will have:
* Captured console evidence for the very first boot, including LEDs, serial output, and timings.
* Exported `/boot/first-boot-report/` artifacts (Markdown, HTML, JSON, and logs) to your lab
  notebook and annotated what each file proves.
* Exercised the self-healing routines by re-running the verifier, investigating simulated failures,
  and confirming the Pi recovers without manual intervention.

## Prerequisites
* Completed artefacts from [Tutorial 1](./tutorial-01-computing-foundations.md) through
  [Tutorial 9](./tutorial-09-building-flashing-pi-image.md), including the bootable SD card or SSD
  created in Tutorial 9.
* Physical access to your Sugarkube Pi, carrier board, or equivalent lab hardware, plus Ethernet and
  power as specified in [Tutorial 6](./tutorial-06-raspberry-pi-hardware-power.md).
* A workstation on the same network with SSH access, `scp`, and the Sugarkube repository cloned.
* Optional but recommended: a USB-to-serial adapter or HDMI capture device so you can log the entire
  boot sequence.

> [!WARNING]
> Keep the Pi on an isolated or trusted network segment for these rehearsals. The image enables
> remote services on first boot—never expose it to production or guest Wi-Fi until you confirm the
> verifier marks everything healthy.

## Lab: Boot, Verify, and Exercise Self-Healing
Create a fresh evidence workspace at `~/sugarkube-labs/tutorial-10/`. Store every log, screenshot,
and transcript there so reviewers can trace each action.

### 1. Prepare your evidence workspace
1. On your workstation, create dedicated directories:

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-10/{notes,logs,media,reports}
   cd ~/sugarkube-labs/tutorial-10
   ```

2. Capture baseline metadata before powering the Pi:

   ```bash
   {
     echo "# Tutorial 10 First Boot Baseline"
     date --iso-8601=seconds
     ip addr show
     arp -an
   } > logs/workstation-baseline.txt
   ```

3. If you have a serial console, start recording the session now so the entire boot is captured:

   ```bash
   screen -L -Logfile logs/pi-serial.log /dev/ttyUSB0 115200
   ```

   Press `Ctrl+A` then `D` to detach and keep recording in the background.

> [!TIP]
> Take a still photo or short video of the hardware layout (power brick, cables, SD card) and save
> it under `media/`. Annotated visuals help reviewers understand your setup when issues arise.

### 2. Cable the Pi and set expectations
1. Connect Ethernet to the same VLAN you prepared in earlier tutorials. Plug in HDMI or your serial
   adapter if available.
2. Insert the SD card or SSD you imaged during Tutorial 9. Double-check it seats firmly in the slot.
3. Review the expected LED pattern: steady red for power, flashing green while the bootloader and
   verifier run, and a heartbeat once the system reaches multi-user mode.

> [!NOTE]
> If the green LED never appears, remove power immediately and re-seat the storage media. Document
> the observation in `notes/README.md` before trying again.

### 3. Power on and monitor first boot
1. Apply power to the Pi. Start a stopwatch so you can timestamp key transitions.
2. Watch the console (serial or HDMI) for `[first-boot]` log lines. When you see
   `first boot automation started`, note the elapsed time in `notes/README.md`.
3. After 5–10 minutes, the Pi should reboot automatically once the filesystem is expanded and
   services are deployed. If you lose console output, wait for network reachability instead of
   unplugging the device.
4. From your workstation, probe the Pi’s IP (replace `192.0.2.10` with the address you assigned):

   ```bash
   ping -c 4 192.0.2.10
   ssh -o StrictHostKeyChecking=accept-new pi@192.0.2.10 'uname -a'
   ```

   Record the SSH fingerprint in `notes/README.md`.

> [!TROUBLESHOOT]
> SSH refusal or timeouts usually mean cloud-init is still applying packages. Run
> `arp -an | grep -i <mac>` from another device to confirm the Pi stays online. If it vanishes,
> check `logs/pi-serial.log` for kernel panics and capture a screenshot before power-cycling.

### 4. Collect `/boot/first-boot-report/`
1. Once logged in, list the report directory:

   ```bash
   sudo ls -R /boot/first-boot-report
   ```

   Expect files such as `summary.md`, `summary.html`, `summary.json`, `self-heal/`, and
   `helm-bundles/`.

2. Copy the reports to your workstation for archival:

   ```bash
   cd ~/sugarkube-labs/tutorial-10
   scp -r pi@192.0.2.10:/boot/first-boot-report reports/pi-first-boot-report
   ```

3. Add quick annotations so future you understands each artifact:

   ```bash
   cat <<'MARKDOWN' > notes/report-index.md
   # First Boot Report Index
   - summary.md — Human-readable checklist from pi_node_verifier.sh.
   - summary.json — Machine-readable status for automation.
   - helm-bundles/*.log — Output from Helm bundle apply hooks.
   - self-heal/ — Journal extracts and retry logs captured by self-healing.
   MARKDOWN
   ```

> [!TIP]
> Open `reports/pi-first-boot-report/summary.html` in a browser and capture a PDF printout or
> screenshot for evidence. Attach the annotated file under `media/`.

### 5. Re-run the verifier and self-heal routines
1. Trigger the bundled verifier again to prove it’s idempotent:

   ```bash
   ssh pi@192.0.2.10 \
     'sudo /opt/sugarkube/pi_node_verifier.sh --log /boot/first-boot-report/manual-rerun.txt'
   ```

   Compare timestamps between `summary.md` and the new log.

2. Inspect the systemd service responsible for first boot:

   ```bash
   ssh pi@192.0.2.10 'sudo systemctl status first-boot.service --no-pager'
   ssh pi@192.0.2.10 'sudo journalctl -u first-boot.service --no-pager | tail -n 200'
   ```

   Save the outputs to `logs/first-boot-service-status.txt` for long-term reference.

3. Review Kubernetes readiness and core services:

   ```bash
   ssh pi@192.0.2.10 'sudo kubectl get nodes'
   ssh pi@192.0.2.10 'sudo kubectl get pods -A'
   ssh pi@192.0.2.10 'sudo docker compose -f /opt/sugarkube/projects/docker-compose.yml ps'
   ```

   Redirect each command with `| tee` if you want inline logs.

> [!WARNING]
> Resist the urge to `sudo systemctl stop first-boot.service` unless you are debugging a hang. The
> self-heal logic relies on that unit to restart dependent services when failures occur.

### 6. Simulate a failure and observe recovery
1. Introduce a harmless error by temporarily disabling token.place:

   ```bash
   ssh pi@192.0.2.10 'sudo systemctl stop token-place.service'
   sleep 30
   ssh pi@192.0.2.10 'sudo systemctl status token-place.service --no-pager'
   ```

2. The self-healing supervisor should restart the service within a minute. Confirm via:

   ```bash
   ssh pi@192.0.2.10 'sudo journalctl -u first-boot.service --no-pager | tail -n 100'
   ssh pi@192.0.2.10 'ls /boot/first-boot-report/self-heal'
   ```

3. Restart the service manually to clear the simulation:

   ```bash
   ssh pi@192.0.2.10 'sudo systemctl start token-place.service'
   ```

4. Document the timestamps, automatic retries, and any new files under `self-heal/` in
   `notes/README.md`.

> [!TROUBLESHOOT]
> If the service does not recover, run `sudo systemctl restart first-boot.service` and inspect
> `/boot/first-boot-report/self-heal/*.log`. Capture the findings and create a remediation plan
> before proceeding.

### 7. Package your evidence
1. Update `notes/README.md` with:
   * Power-on timestamps and LED observations.
   * SSH fingerprints, IP assignments, and verifier results.
   * Any troubleshooting steps, including commands that failed and how you resolved them.

2. Archive the entire lab bundle:

   ```bash
   cd ~/sugarkube-labs
   tar -czf tutorial-10-evidence.tar.gz tutorial-10
   ```

   Store the archive with restricted permissions or upload it to your team’s secure evidence store.

## Milestone Checklist
Use this checklist to verify you achieved each objective before moving on.

- [ ] Captured first boot observations (console log, LED notes, timestamps) and stored them under
      `~/sugarkube-labs/tutorial-10/`.
- [ ] Archived `/boot/first-boot-report/` plus manual verifier rerun logs with annotations that
      explain each artifact’s purpose.
- [ ] Simulated a recoverable failure, observed the self-healing response, and documented the
      outcome in your lab notes.

## Next Steps
When you are satisfied with the evidence, continue to [Tutorial 11: Storage Migration and Long-Term
Maintenance](./index.md#tutorial-11-storage-migration-and-long-term-maintenance) (once published).
You will clone the boot media, validate SSD migrations, and build a sustainable maintenance cadence.
