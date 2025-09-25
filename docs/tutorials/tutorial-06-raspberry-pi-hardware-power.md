# Tutorial 6: Raspberry Pi Hardware and Power Design

## Overview
This guide continues the [Sugarkube Tutorial Roadmap](./index.md#tutorial-6-raspberry-pi-hardware-and-power-design)
by moving from software drills to the physical aluminium extrusion Sugarkube cube. You will identify
every component in the kit—including the 3D-printed Pi carrier and solar charge gear—wire clean power
delivery, and validate that the Raspberry Pi stack can run safely under load. The lab combines
assembly tasks with measurement checkpoints so you build the muscle memory required to troubleshoot
the real outdoor hardware later in the series.

By the end you will have:
* Documented your hardware and solar inventory with annotated photos.
* Routed and tested the 5 V power chain feeding the Pi, accessories, cooling gear, and charge
  controller outputs.
* Captured multimeter readings, solar open-circuit voltages, thermal measurements, and stress-test
  logs that prove stability.
* Filed a workspace report so future you (or teammates) can replicate the setup confidently.

## Prerequisites
* Hands-on safety practices and component labels from
  [Tutorial 1](./tutorial-01-computing-foundations.md).
* Terminal and documentation habits from
  [Tutorial 2](./tutorial-02-navigating-linux-terminal.md) for recording logs.
* Network diagram and router access from
  [Tutorial 3](./tutorial-03-networking-internet-basics.md) so you can plan Ethernet runs.
* Git workflow familiarity from
  [Tutorial 4](./tutorial-04-version-control-collaboration.md) to version-control your lab notes.
* Automation workspace from
  [Tutorial 5](./tutorial-05-programming-for-operations.md) for organising scripts and evidence.
* Hardware kit that includes a Raspberry Pi 4 (4 GB or 8 GB recommended), USB-C or PD power supply,
  powered USB hub, microSD or SSD storage, multimeter, jumper wires, standoffs, aluminium extrusion
  frame, solar charge controller, MC4 connectors, wiring harness, and the 3D-printed Sugarkube
  Pi carrier. Order parts ahead of time using reputable vendors such as
  [Pimoroni](https://shop.pimoroni.com/) or
  [SparkFun](https://www.sparkfun.com/) if you still need components.
* Recommended reading: [Solar Basics](../solar_basics.md) for panel and charge-controller theory, and
  the [Pi Carrier Field Guide](../pi_carrier_field_guide.md) for printed-part orientation tips.

> [!WARNING]
> Perform the lab on an anti-static mat or wooden table. Avoid carpeted rooms, and unplug the power
> supply whenever you manipulate wiring. If you feel static, discharge by touching a grounded metal
> object before handling electronics.

## Lab: Assemble and Validate the Sugarkube Hardware Stack
Complete the steps in order. Store all notes, images, and measurement logs in
`~/sugarkube-tutorials/tutorial-06/`. Create subfolders named `photos/`, `measurements/`, and
`reports/` to keep evidence organised.

### 1. Inventory and photograph each component
1. Create your lab directory and initialise version control:

   ```bash
   mkdir -p ~/sugarkube-tutorials/tutorial-06/{photos,measurements,reports}
   cd ~/sugarkube-tutorials/tutorial-06
   git init
   ```

2. Lay out all hardware on the anti-static mat. Include Pi board(s), power supplies, fans, hubs,
   cables, fasteners, and the enclosure panels.
3. Capture a top-down photo. Save it as `photos/01-kit-overview.jpg` and label each component using
   your preferred image editor (even simple numbered arrows plus a legend works).
4. Record a bill of materials file:

   ```bash
   cat <<'BOM' > reports/bill-of-materials.md
   # Tutorial 6 Bill of Materials

   | Item | Quantity | Notes |
   | --- | --- | --- |
   | Raspberry Pi 4 Model B (8 GB) | 1 | Includes microSD card slot |
   | USB-C 5.1V/5A power supply | 1 | Official Raspberry Pi PSU |
   | Powered USB 3.0 hub | 1 | Provides SSD power |
   | 256 GB SSD with USB enclosure | 1 | boot media |
   | 32 GB microSD card | 1 | recovery media |
   | 5 V fan with heatsink | 1 | for enclosure airflow |
   | Multimeter | 1 | set to DC voltage mode |
   | M2.5 standoff kit | 1 | 12 mm length |
   | Aluminium extrusion cube kit | 1 | cut to Sugarkube dimensions |
   | 3D-printed Pi carrier assembly | 1 | printed in PETG/ABS |
   | 100 W solar panel with MC4 leads | 1 | sized for cube roof |
   | MPPT solar charge controller (12 V) | 1 | outputs 5 V via buck converter |
   | Weather-resistant wiring ties | 6 | for cable management |
   BOM
   ```

5. Commit the baseline documentation:

   ```bash
   git add photos/ reports/bill-of-materials.md
   git commit -m "Document Sugarkube hardware inventory"
   ```

> [!TIP]
> If you are missing a component, flag it now. Record an action item in `reports/bill-of-materials.md`
> so you do not forget to order replacements before continuing.

### 2. Prepare the enclosure and mounting hardware
1. Dry-fit the aluminium extrusion frame, corner cubes, and acrylic/metal panels without screws to
   understand their orientation. Confirm the roof panel has mounting holes for the solar brackets.
2. Install threaded inserts or standoffs per the Sugarkube build guide. Use a soldering iron or
   heat-set tool if required and note the temperature setting in `reports/workspace-log.md`.
3. Test-fit the 3D-printed Pi carrier on its rails or standoffs. Verify cable passthrough slots align
   with the carrier’s harness and annotate any sanding or filing you perform.
4. Mark the planned entry point for the solar wiring loom (gland or grommet). Note any weather sealing
   material you will add later.

   ```bash
   cat <<'LOG' > reports/workspace-log.md
   # Tutorial 6 Workspace Log

   - 09:00 — Heat-set inserts installed at 180°C using Hakko FX-888D.
   - 09:15 — Verified standoffs align with Pi mounting holes.
   LOG
   ```

5. Photograph the assembled frame (`photos/02-enclosure-frame.jpg`). Ensure screw holes, carrier rails,
   and cable passthroughs are visible.
6. Update the workspace log with any adjustments, such as sanding edges, swapping screws for longer
   alternatives, or rotating solar brackets.
7. Commit the changes:

   ```bash
   git add reports/workspace-log.md photos/02-enclosure-frame.jpg
   git commit -m "Assemble enclosure frame and log adjustments"
   ```

> [!NOTE]
> If you do not yet own the physical enclosure, print the layout diagram from `docs/hardware/enclosure`
> (or sketch your own) and complete the step by annotating cable routes on paper. Save the sketch as
> `photos/02-enclosure-frame-sketched.jpg` for future reference.

### 3. Route and label the power chain
1. Place the powered USB hub, SSD, and solar charge controller within the enclosure. Plan cable paths
   so USB and fan cables do not cross the higher-voltage solar leads.
2. Mount the charge controller to a panel or DIN rail. Leave clearance for airflow around the buck
   converter that drops 12 V to 5 V.
3. Terminate the solar input with MC4 connectors or gland-protected leads. Label the polarity clearly
   and route the cables through the entry point you marked earlier. Capture before/after photos
   (`photos/03a-cable-before.jpg`, `photos/03b-cable-after.jpg`).
4. Label both ends of every cable with masking tape or heat-shrink labels (e.g., “Pi USB-C”, “Hub
   Input”, “Fan 5V”, “Solar +”, “Solar -”). Update `reports/workspace-log.md` with the labeling scheme.
5. Create a power map drawing showing how solar and mains power converge. Include the solar array,
   charge controller, buck converter, and 5 V distribution. Save the annotated diagram as
   `photos/03c-power-map.jpg`.
6. Record expected voltage values in `measurements/power-plan.csv`:

   ```bash
   cat <<'CSV' > measurements/power-plan.csv
   node,expected_voltage,notes
   usb-c-input,5.1,Official PSU specification
   hub-output,5.0,Measured at idle
   solar-array-open-circuit,18.0,Depends on panel model
   charge-controller-output,5.1,Buck converter feeding USB hub
   pi-gpio-5v,5.0,Measure on pin 2 or 4 relative to pin 6 ground
   fan-header,5.0,Inline switch installed
   ssd-enclosure,5.0,Drawn from powered hub port 1
   CSV
   ```

6. Commit documentation so far:

   ```bash
   git add photos/03a-cable-before.jpg photos/03b-cable-after.jpg photos/03c-power-map.jpg \
     measurements/power-plan.csv reports/workspace-log.md
   git commit -m "Route and document Sugarkube power chain"
   ```

> [!WARNING]
> Never power the Pi from two sources simultaneously (e.g., USB-C PSU and PoE hat). Doing so risks
> back-feeding and damaging the board. Stick to a single, known-good supply throughout this lab.

### 4. Mount the Raspberry Pi and Pi carrier harness
1. Secure the Pi carrier to its rails or standoffs. Confirm the printed latches seat fully without
   stressing the board.
2. Mount the Raspberry Pi onto the carrier. Tighten screws until snug but avoid flexing the PCB.
3. Attach the fan and heatsink assembly. Ensure airflow is directed across the CPU and RAM and that
   ducts align with the carrier’s cut-outs.
4. Connect the SSD enclosure to the powered hub. Route the cable through the carrier strain-relief
   features so it does not tug on the USB-C port.
5. Insert the microSD card (even if you will boot from SSD later) to ease firmware updates and to
   secure the carrier’s card retention clip.
6. Update `reports/workspace-log.md` with the mounting order, torque values, and any carrier fit
   adjustments.
7. Photograph the partially assembled interior (`photos/04-mounting-complete.jpg`) and commit:

   ```bash
   git add reports/workspace-log.md photos/04-mounting-complete.jpg
   git commit -m "Mount Raspberry Pi and accessories"
   ```

### 5. Validate voltage with a multimeter
1. Plug the power supply into a surge-protected outlet but leave the Pi off. If daylight is available,
   connect the solar panel and ensure the charge controller indicates charging.
2. Set the multimeter to DC voltage. Probe the USB hub output without load to confirm it reads close to
   5.0 V. Record the value in `measurements/voltage-readings.csv` with timestamp:

   ```bash
   cat <<'CSV' > measurements/voltage-readings.csv
   timestamp,location,measured_voltage
   $(date -u +"%Y-%m-%dT%H:%M:%SZ"),hub-output,5.08
   CSV
   ```

3. Measure the solar array open-circuit voltage at the MC4 leads (disconnect from controller first).
   Reconnect the leads, then power the Pi and repeat measurements on the charge controller output, GPIO
   5 V pin, and fan header. Append readings using `tee` so you keep a command transcript:

   ```bash
   printf "%s,%s,%.2f\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "solar-array-open-circuit" 19.20 | tee -a measurements/voltage-readings.csv
   printf "%s,%s,%.2f\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "charge-controller-output" 5.12 | tee -a measurements/voltage-readings.csv
   printf "%s,%s,%.2f\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "pi-gpio-5v" 5.03 | tee -a measurements/voltage-readings.csv
   printf "%s,%s,%.2f\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "fan-header" 4.97 | tee -a measurements/voltage-readings.csv
   ```

4. Compare actual vs. expected values. Update `reports/workspace-log.md` with any deviations or
   corrective actions (e.g., reseating cables).
5. Commit the measurement log:

   ```bash
   git add measurements/voltage-readings.csv reports/workspace-log.md
   git commit -m "Capture multimeter readings for power validation"
   ```

> [!TIP]
> If your multimeter supports min/max recording, enable it while wiggling cables gently. Spikes or
> drops indicate loose connectors that should be reworked before proceeding. Shade the solar panel
> briefly while observing the charge-controller output so you know how the system reacts to clouds.

### 6. Stress-test thermals and document results
1. Boot the Pi using your existing Sugarkube image or Raspberry Pi OS. SSH into it from your
   workstation. If you need credentials, create a temporary user now and rotate its credentials after
   the lab.
2. Install stress tools:

   ```bash
   sudo apt update
   sudo apt install -y stress-ng lm-sensors
   ```

3. Start a combined CPU and memory stress test for 10 minutes while logging temperatures:

   ```bash
   mkdir -p ~/tutorial-06-logs
   stress-ng --cpu 4 --vm 2 --vm-bytes 512M --timeout 10m --metrics-brief | tee ~/tutorial-06-logs/stress-ng.txt
   ```

4. In a second terminal, sample temperatures every 30 seconds:

   ```bash
   watch -n 30 "vcgencmd measure_temp; sensors" | tee ~/tutorial-06-logs/thermal-watch.txt
   ```

   Stop `watch` after the stress test completes (`Ctrl+C`).

5. Copy the logs back to your workstation (replace `pi@hostname` with your device):

   ```bash
   scp pi@hostname:~/tutorial-06-logs/*.txt ~/sugarkube-tutorials/tutorial-06/measurements/
   ```

6. Plot the temperature trend using a notebook or spreadsheet. Save the chart as
   `measurements/thermal-trend.png`.
7. Summarise findings in `reports/thermal-summary.md`:

   ```bash
   cat <<'SUMMARY' > reports/thermal-summary.md
   # Thermal Test Summary

   - Max CPU temp: 68°C at 8m30s (below 80°C throttle threshold).
   - Fan maintained stable airflow; no power brownouts observed.
   - Recommendation: clean dust filters monthly and re-run stress test after hardware changes.
   SUMMARY
   ```

8. Commit all thermal evidence:

   ```bash
   git add measurements/thermal-trend.png measurements/stress-ng.txt \
     measurements/thermal-watch.txt reports/thermal-summary.md
   git commit -m "Record thermal stress test results"
   ```

> [!NOTE]
> If you cannot run `stress-ng` on real hardware, simulate the step with
> [Raspberry Pi OS in QEMU](https://www.raspberrypi.com/documentation/computers/virtual-machines.html)
> or review published benchmarks from trusted sources. Document the substitute evidence clearly in
> `reports/thermal-summary.md`.

### 7. Publish a workspace report
1. Export a final PDF or Markdown report summarising the build. Include:
   * Bill of materials snapshot.
   * Power measurements with comparison table.
   * Thermal chart and interpretation.
   * Photos of the finished build.

2. Use Git to create a tagged release for your lab evidence:

   ```bash
   git tag -a tutorial-06-complete -m "Sugarkube hardware and power lab complete"
   git push origin main --tags  # adjust remote name if needed
   ```

3. Share the report with collaborators and solicit feedback on readability and completeness.
4. Archive the physical workspace by storing spare screws, lab notes, and measurement tools in a
   labelled container so you can resume work quickly next time.

## Milestone Checklist
Use this checklist to verify you met the roadmap milestones. Mark each item complete in your lab
repository README or tracking tool.

### Milestone 1: Assemble the enclosure and record build evidence
- [ ] Captured `photos/01-kit-overview.jpg` with labelled components (including solar gear).
- [ ] Logged enclosure assembly steps, Pi carrier fit adjustments, and temperatures in
  `reports/workspace-log.md`.
- [ ] Produced a time-lapse, annotated photos, or equivalent visual record of the build sequence and
  solar bracket placement.

### Milestone 2: Perform voltage and continuity checks
- [ ] Completed `measurements/power-plan.csv` before powering on hardware, including solar nodes.
- [ ] Recorded live readings (hub, solar array, charge controller, Pi rails) in
  `measurements/voltage-readings.csv` after powering on.
- [ ] Compared expected vs. actual values and documented remediation actions.

### Milestone 3: Stress-test thermal management and document strategies
- [ ] Ran the `stress-ng` workload and saved output under `measurements/`.
- [ ] Captured temperature samples and plotted `measurements/thermal-trend.png`, noting weather or
  solar conditions.
- [ ] Summarised results and mitigation ideas in `reports/thermal-summary.md`, including outdoor heat
  considerations.

## Next Steps
Continue to [Tutorial 7: Kubernetes and Container Fundamentals](./tutorial-07-kubernetes-container-fundamentals.md)
to map your validated hardware to real workloads. The next guide introduces container orchestration
concepts and a local Kubernetes lab you can run before flashing the actual Sugarkube image.
