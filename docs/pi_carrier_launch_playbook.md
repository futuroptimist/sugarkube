---
personas:
  - hardware
  - software
---

# Pi Carrier Launch Playbook

The Pi Carrier Launch Playbook stitches every quickstart, builder note, and troubleshooting
checklist into one narrative so operators can move from a sealed SD card to a healthy, observable
k3s cluster without hunting across the docs. It pulls together the automation shipped in this
repo—installers, flashers, verifiers, and self-healing services—and shows when to lean on each tool.

This guide complements (rather than replaces) the focused references such as
[`pi_image_quickstart.md`](./pi_image_quickstart.md),
[`pi_image_builder_design.md`](./pi_image_builder_design.md), and
[`pi_headless_provisioning.md`](./pi_headless_provisioning.md). Skim the fast path to get a Pi
booted in minutes, then jump into the persona walkthroughs or deep references when you need
additional context or want to adapt the workflow for teams.

---

## 10-Minute Fast Path

This fast path assumes you have one workstation, one Pi 5 with storage attached, and network access.
Each step references automation that ships with the repository. Expect roughly ten minutes of active
work; the downloads and flash runs are unattended.

1. **Prep tooling:**
   ```bash
   git clone https://github.com/futuroptimist/sugarkube.git
   cd sugarkube
   just codespaces-bootstrap
   ```
   The bootstrap target installs `gh`, `curl`, flashing dependencies, and Python requirements. Prefer
   `make codespaces-bootstrap` when you would rather stay inside the Makefile. Skip this step inside
   Codespaces where the bootstrap happens automatically.

2. **Grab the latest release:**
   ```bash
   ./scripts/install_sugarkube_image.sh --dir ~/sugarkube/images
   ```
   The installer resolves the newest GitHub Release, resumes partial downloads, verifies SHA-256
   signatures, expands the `.img.xz`, and emits a refreshed `.img.sha256` file under
   `~/sugarkube/images/`.

3. **Flash removable media:**
   ```bash
   sudo make flash-pi FLASH_DEVICE=/dev/sdX
   ```
   Replace `/dev/sdX` with the detected SD card or USB device. The `flash-pi` recipe chains the
   installer above, pipes the expanded image into `flash_pi_media.sh`, verifies the written bytes,
   and powers the device off when complete.

4. **Boot and wait for first-boot automation.** Watch the console or check
   `/boot/first-boot-report/` after a few minutes. `first-boot.service` stretches the filesystem,
   runs `pi_node_verifier.sh`, and writes Markdown/HTML/JSON summaries to the boot partition for
   offline review.

5. **Confirm cluster health:**
   ```bash
   ssh sugarkube@<pi-host>
   sudo kubectl get nodes
   sudo systemctl status projects-compose.service
   ```
   Expect the node to report `Ready` and the compose service to be `active (running)`.

6. **Replay token.place samples:**
   ```bash
   /opt/sugarkube/token_place_replay_samples.py
   ```
   The helper generates JSON transcripts under `~/sugarkube/reports/token-place-samples/`, proving
   token.place and dspace respond before inviting external traffic.

7. **Verify observability taps:**
   - `curl http://<pi-host>:12345/metrics` (Grafana Agent aggregate)
   - `curl http://<pi-host>:9100/metrics` (node exporter)
   - Visit `http://<pi-host>:19999` (Netdata)

8. **Optional: rehearse SSD migration** to build muscle memory before plugging in a drive:
   ```bash
   sudo ./scripts/ssd_clone.py --target /dev/sda --dry-run
   ```

9. **Optional: rehearse cluster join** for multi-node fleets:
   ```bash
   make rehearse-join REHEARSAL_ARGS="sugar-control.local --agents sugar-worker.local"
   ```

10. **Record the success:** capture the `/boot/first-boot-report/` directory and refresh the
    hardware boot badge via
    [`pi_image_contributor_guide.md`](./pi_image_contributor_guide.md#record-hardware-boot-runs).

---

## Persona Walkthroughs

Different teams approach the Pi carrier with unique constraints. These persona playbooks highlight
how to tailor the automation and documentation for each audience while preserving the ten-minute
fast path above.

### Solo builder (home lab or field deployer)

- **Keep a printable checklist nearby:** Generate `pi_carrier_field_guide.pdf` with `make
  field-guide` and pair it with the QR labels so the quickstart and troubleshooting docs stay within
  reach.
- **Operate offline when needed:** Cache releases with `./scripts/install_sugarkube_image.sh
  --download-only`. Flash from a laptop using the cached `.img.xz` and run `pi_node_verifier.sh`
  locally after boot to surface configuration issues without internet access.
- **Simplify secrets management:** Follow
  [`pi_headless_provisioning.md`](./pi_headless_provisioning.md) to stage Wi-Fi credentials and
  tokens in `secrets.env` files consumed by cloud-init so SD cards stay clean of long-lived secrets.
- **Verify before leaving the site:** Run `make support-bundle` or
  `./scripts/collect_support_bundle.py --target /boot/first-boot-report` to archive first-boot logs
  for future debugging. The helper stores copied directories under `targets/` in the bundle so the
  exported reports remain alongside the captured command output. Prefer the unified CLI? Use
  `python -m sugarkube_toolkit pi support-bundle --dry-run -- <pi-host>` to preview the invocation,
  then rerun without `--dry-run` when you're ready to capture diagnostics.

### Classroom facilitator (multiple Pis, shared bench)

- **Parallelize downloads and flashing:** Use the flash report helper from the fast path with unique
  `--device` values in separate terminals. The Markdown reports include device serial numbers,
  making it easy to match hardware to lab stations.
- **Pre-stage presets:** Render Raspberry Pi Imager presets with
  `scripts/render_pi_imager_preset.py` so each student can open advanced options with hostnames,
  users, Wi-Fi credentials, and SSH keys ready to apply.
- **Guide verification visually:** Point learners to the [Pi Image
  Flowcharts](./pi_image_flowcharts.md) and [Pi Boot Troubleshooting](./pi_boot_troubleshooting.md)
  matrix. Embed these diagrams in slides or printouts so teams can self-serve while you circulate.
- **Collect progress artifacts:** Encourage students to upload their `/boot/first-boot-report/`
  folders to a shared drive. These reports drive retrospective analysis without requiring persistent
  SSH access.

### Maintainer (release engineer or automation contributor)

- **Keep builds reproducible:** Review [`pi_image_builder_design.md`](./pi_image_builder_design.md)
  to understand pi-gen stages, cached artifacts, and provenance metadata captured by
  `scripts/create_build_metadata.py` and `scripts/generate_release_manifest.py`.
- **Exercise every automation path:**
  - `pre-commit run --all-files`
  - `pytest --cov --cov-fail-under=100` to guarantee 100% patch coverage on the first test run.
  - `pyspelling -c .spellcheck.yaml`
  - `linkchecker --no-warnings README.md docs/`
  - `git diff --cached | ./scripts/scan-secrets.py` These commands mirror CI expectations and keep
    the trunk green.
- **Use smoke tests before cutting releases:** Run `make doctor` to chain download, checksum, flash
  dry-run, and linting. Follow with `scripts/pi_smoke_test.py --host <pi>` to assert k3s readiness,
  container health, and service reachability over SSH.
- **Refresh the documentation loop:** Cross-reference
  [`pi_image_contributor_guide.md`](./pi_image_contributor_guide.md) whenever scripts or workflows
  change. Update the new Playbook alongside the quickstart and ensure `make docs-verify` stays clean
  so docs and automation never drift.

---

## Deep Reference Sections

The following sections map each phase of the journey to the detailed guides, wiring photos, and
helper scripts that already ship with the repository. Dip into these references when the fast path
needs customization or when debugging an unfamiliar scenario.

### Hardware assembly & wiring

- Start with [`raspi_cluster_setup.md`](./raspi_cluster_setup.md) for the bill of materials, Pi
  carrier assembly order, and tips on KVM or power distribution.
- Review [`pi_cluster_carrier.md`](./pi_cluster_carrier.md) for mechanical drawings and mounting
  hardware callouts.
- Confirm wiring against the annotated photos in [`hardware/README.md`](../hardware/README.md) and
  the printable [Pi Carrier Field Guide](./pi_carrier_field_guide.md#hardware-overview).

### Image lifecycle & automation

- [`pi_image_quickstart.md`](./pi_image_quickstart.md) covers manual builds, GitHub Actions
  releases, checksum verification, flashing options, and observability smoke checks.
- [`pi_image_builder_design.md`](./pi_image_builder_design.md) dives into pi-gen stages, container
  layout, build caches, and provenance metadata.
- [`pi_image_contributor_guide.md`](./pi_image_contributor_guide.md) maps automation scripts to
  their documentation counterparts and explains how CI enforces spellcheck/linkcheck plus linting.
- [`pi_support_bundles.md`](./pi_support_bundles.md) and
  [`pi_workflow_notifications.md`](./pi_workflow_notifications.md) help you monitor long builds and
  archive debugging artifacts.

### Networking, access, and exposure

- [`network_setup.md`](./network_setup.md) documents static IP planning, VLANs, and DHCP
  reservations.
- [`pi_image_cloudflare.md`](./pi_image_cloudflare.md) explains how to expose token.place and dspace
  via Cloudflare Tunnel, including Zero Trust policies and DNS wiring.
- [`pi_headless_provisioning.md`](./pi_headless_provisioning.md) provides a fully headless boot path
  via cloud-init, secrets templates, and verifier integration.
- [`pi_multi_node_join_rehearsal.md`](./pi_multi_node_join_rehearsal.md) rehearses node joins
  without touching production clusters.

### Post-boot validation & self-healing

- [`pi_node_verifier.sh`](../scripts/pi_node_verifier.sh) powers the first-boot report and can be
  run on demand; see [`pi_smoke_test.py`](../scripts/pi_smoke_test.py) for remote execution across
  hosts.
- [`ssd_clone_service.py`](../scripts/ssd_clone_service.py) and
  [`ssd_clone.py`](../scripts/ssd_clone.py) automate SD → SSD migration with resume support and
  reporting.
- [`sugarkube-self-heal@.service`](../scripts/systemd/self-heal-service/README.md) and
  [`self_heal_service.py`](../scripts/self_heal_service.py) document automated remediation flows
  when container pulls or cloud-init runs fail. The README now calls out log locations and links to
  regression coverage (`tests/self_heal_service_docs_test.py`) so operators know where to start
  their incident response.
- [`ssd_post_clone_validate.py`](../scripts/ssd_post_clone_validate.py) checks EEPROM boot order,
  `/etc/fstab`, and stress tests new storage.
- [`rollback_to_sd.sh`](../scripts/rollback_to_sd.sh) provides a guided rollback if SSD validation
  fails.

---

## Troubleshooting & Recovery

- Lean on [`pi_boot_troubleshooting.md`](./pi_boot_troubleshooting.md) for LED codes, journal
  commands, and recovery decision trees.
- For networking surprises, pair `network_setup.md` with the `make support-bundle` helper to collect
  diagnostics before and after applying fixes.
- If observability dashboards go dark, rerun `token_place_replay_samples.py` and
  `scripts/pi_node_verifier.sh --skip-compose=false` to regenerate first-boot reports and confirm
  container health. When `projects-compose` is intentionally offline, pass `--skip-compose`
  instead to bypass the service probe (regression coverage:
  `tests/pi_node_verifier_skip_test.bats` ensures the flag works).
- When SSD migrations or clones stall, combine `ssd_clone.py --resume` with the Markdown reports
  under `~/sugarkube/reports/ssd-clone/` and reference [`ssd_recovery.md`](./ssd_recovery.md) for
  fallback to SD cards.

---

## Appendix: Handy Commands

- **Download + verify + flash in one go:**
  ```bash
  sudo make flash-pi FLASH_DEVICE=/dev/sdX
  ```
- **Generate flash + verification report:**
  ```bash
  sudo ./scripts/flash_pi_media_report.py \
    --image ~/sugarkube/images/sugarkube.img.xz \
    --device /dev/sdX \
    --assume-yes
  ```
- **Run verifier remotely:**
  ```bash
  python scripts/pi_smoke_test.py --host <pi-host>
  ```
- **Collect support bundle:**
  ```bash
  make support-bundle SUPPORT_BUNDLE_ARGS="--host <pi-host>"
  ```
- **Rehearse multi-node join:**
  ```bash
  make rehearse-join REHEARSAL_ARGS="sugar-control.local --agents sugar-worker.local"
  ```
- **Validate SSD health:**
  ```bash
  python scripts/ssd_health_monitor.py --output ~/sugarkube/reports/ssd-health/
  ```

Keep this appendix updated as automation grows so operators have a single lookup table for the most
common tasks.
