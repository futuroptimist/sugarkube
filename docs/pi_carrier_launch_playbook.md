# Pi Carrier Launch Playbook

> A single, end-to-end manual for downloading, flashing, booting, migrating, and
> operating the Sugarkube Pi carrier. Start here when you need a guided path or
> want to share a consistent workflow across teams.

## How to use this playbook

1. **Skim the [10-minute fast path](#10-minute-fast-path)** when you only need a
   refresher before heading to the workbench.
2. **Jump to [persona walkthroughs](#persona-walkthroughs)** for curated task
   lists that match your role.
3. **Dive into the [deep reference](#deep-reference)** to explore every helper
   script, report, and troubleshooting aid.

The playbook pulls content from previously separate docs: the quickstart,
builder design notes, Cloudflare and networking guides, SSD migration docs, and
first-boot troubleshooting references. Everything remains available as
standalone pages, but this guide stitches the journey together with inline
checklists and links so you can print, share, or iterate on a single source of
truth.

## 10-minute fast path

1. **Download or build the image**
   - Run the installer:

     ```bash
     INSTALL_URL=https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/\
install_sugarkube_image.sh
     curl -fsSL "$INSTALL_URL" | bash
     ```

   - Or run `./scripts/build_pi_image.sh` inside the repo for a local build.
   - Optional:

     ```bash
     sudo make qemu-smoke \
       QEMU_SMOKE_IMAGE=deploy/sugarkube.img.xz
     ```

     Confirm first boot before touching hardware.
2. **Flash removable media**
   - Generate a flash report:

     ```bash
     sudo ./scripts/flash_pi_media_report.py \
       --image ~/sugarkube/images/sugarkube.img.xz \
       --device /dev/sdX \
       --assume-yes
     ```

   - Prefer Raspberry Pi Imager? Use the presets in `docs/templates/pi-imager/`.
3. **Boot + verify health**
   - Power the Pi and wait for the LEDs to settle.
   - `sudo systemctl status k3s-ready.target` and
     `sudo systemctl status projects-compose.service` confirm cluster readiness.
   - Run `/opt/sugarkube/token_place_replay_samples.py` to replay bundled API
     checks and inspect `/boot/first-boot-report/` for first-boot results.
4. **Clone to SSD when ready**
   - Connect the SSD and run:

     ```bash
     sudo ./scripts/ssd_clone.py --resume
     ```

   - Validate with:

     ```bash
     sudo ./scripts/ssd_post_clone_validate.py
     ```

     before rebooting.
5. **Capture support data on demand**
   - `make support-bundle SUPPORT_BUNDLE_HOST=pi-a.local` gathers kubectl logs,
     compose status, and systemd traces into `support-bundles/`.

Print the [Pi Carrier Field Guide](./pi_carrier_field_guide.pdf) and stick the
[QR labels](./pi_carrier_qr_labels.md) near your rig so builders always land on
this playbook.

## Persona walkthroughs

### Solo builder

- Use the fast path to download → flash → boot in one sitting.
- Scan the [LED & Troubleshooting Matrix](./pi_boot_troubleshooting.md) while
  the system comes online.
- After first boot, follow the
  [SSD clone workflow](./pi_image_quickstart.md#automatic-ssd-cloning-on-first-boot)
  and run the validator before moving hardware into production.
- Archive the generated `first-boot-report/` plus the flash report so you can
  diff against future runs.

### Classroom facilitator

- Pre-download the latest image with `scripts/install_sugarkube_image.sh` and
  preload SD cards using `make flash-pi` so students only handle the boot and
  verification steps.
- Provide printed copies of the [Field Guide](./pi_carrier_field_guide.pdf) and
  a short link/QR to this playbook.
- Use the `reports/` artifacts (flash, first boot, SSD validation) as grading
  evidence or troubleshooting handouts.
- Encourage learners to explore optional branches: running
  `scripts/pi_multi_node_join_rehearsal.py` to simulate scaling or replaying the
  token.place samples to confirm app readiness.

### Maintainer / SRE

- Schedule monthly rebuilds with the pi-image workflow and archive the
  `qemu-smoke` artifacts for regression tracking.
- After updating automation, run `make doctor` to chain download, linting, and
  flash dry-runs before shipping changes.
- Use the [telemetry hooks](./pi_image_telemetry.md) to publish anonymized health data
  when clusters move into the field.
- Capture support bundles before opening issues and upload them alongside
  `docs/status/hardware-boot.json` updates so the README badge stays fresh.

## Deep reference

### Build and download

- **Automated installer:**
  [`scripts/install_sugarkube_image.sh`](../scripts/install_sugarkube_image.sh)
  handles GitHub CLI bootstrapping, release discovery, checksum verification,
  and cache management. Invoke `--help` for advanced flags.
- **Manual workflow artifacts:** The pi-image GitHub Actions workflow produces
  signed `.img.xz` archives with provenance manifests. See the
  [builder design document](./pi_image_builder_design.md) for stage diagrams,
  caching strategy, and supply-chain notes.
- **Offline/air-gapped prep:** Use `scripts/download_pi_image.sh --asset` to
  mirror release artifacts locally. The playbook pairs well with
  [`scripts/create_build_metadata.py`](../scripts/create_build_metadata.py) and
  [`scripts/generate_release_manifest.py`](../scripts/generate_release_manifest.py)
  when you need auditable metadata.

### Flashing & provisioning

- **Flash helpers:** `scripts/flash_pi_media.sh` streams `.img` or `.img.xz`
  directly to devices with verification and auto-eject support. The PowerShell
  wrapper covers Windows operators.
- **Report generator:** `scripts/flash_pi_media_report.py` captures Markdown,
  HTML, and JSON flash summaries plus optional cloud-init diffs under
  `~/sugarkube/reports/`.
- **Pi Imager presets:** Render customized JSON with
  `scripts/render_pi_imager_preset.py` to pre-populate hostnames, Wi-Fi, and SSH
  keys before classroom events.
- **Headless secrets:** Follow [Pi Headless Provisioning](./pi_headless_provisioning.md)
  to inject Wi-Fi credentials and API tokens without committing secrets.

### First boot confidence

- `first-boot.service` coordinates filesystem expansion, retries
  `pi_node_verifier.sh`, and publishes Markdown/HTML/JSON reports to
  `/boot/first-boot-report/`. The
  [service design notes](./pi_image_builder_design.md#first-boot-automation)
  include unit dependencies and failure handling.
- The [Pi Smoke Test](./pi_smoke_test.md) harness plus the QEMU variant
  (`scripts/qemu_pi_smoke_test.py`) validate images before hardware.
- The [Troubleshooting Matrix](./pi_boot_troubleshooting.md) maps LED patterns,
  journal locations, and suggested fixes when the happy path fails.

### SSD migration & storage

- Automate cloning with `scripts/ssd_clone_service.py` (systemd unit) or the
  manual `scripts/ssd_clone.py` helper. Dry-run support and resume logic reduce
  surprises.
- Validate migrations via `scripts/ssd_post_clone_validate.py` to confirm boot
  order, `/etc/fstab`, and stress tests.
- Roll back safely with `scripts/rollback_to_sd.sh` and follow the
  [SSD recovery guide](./ssd_recovery.md) for controlled failovers.
- Monitor long-term health using `scripts/ssd_health_monitor.py`, which reads
  SMART metrics and publishes Markdown summaries.

### Observability & workloads

- `k3s-ready.target` and `projects-compose.service` ensure Kubernetes and the
  bundled compose apps stay healthy. Review the [Helm bundle hooks](./pi_helm_bundles.md)
  for applying pinned workloads atomically.
- Sample data under `samples/token_place/` plus
  `/opt/sugarkube/token_place_replay_samples.py` confirm token.place works out
  of the box.
- Optional telemetry uploads are covered in [Sugarkube Telemetry](./pi_image_telemetry.md)
  with systemd timers and opt-in environment variables.
- The [Workflow Artifact Notifier](./pi_workflow_notifications.md) posts desktop
  alerts when release runs finish uploading assets.

### Support, recovery & scaling

- Generate support bundles with `scripts/collect_support_bundle.py` (Makefile
  and Just wrappers available) to gather kubectl events, compose logs, and
  systemd blame outputs.
- Practice scale-out using `scripts/pi_multi_node_join_rehearsal.py`, which
  validates join tokens and node readiness before touching production.
- Export redacted kubeconfigs via `scripts/cloud-init/export-kubeconfig.sh`
  so operators can connect without SSH.
- Use the [self-heal automation](./pi_boot_troubleshooting.md#self-heal-automation)
  to understand how the system retries container pulls, cleans cloud-init, and
  escalates to `rescue.target`.

### Hardware assembly & wiring references

- Walk through enclosure assembly in [Build Guide](./build_guide.md) with photos
  of each mechanical step.
- Mount Raspberry Pis using the standoff map in
  [Pi Cluster Carrier](./pi_cluster_carrier.md) and reference the wiring photos
  for PoE hats, fans, and cable routing.
- Review [Electronics Schematics](./electronics_schematics.md) and
  [Power System Design](./power_system_design.md) before wiring the solar
  components or aquarium aerator.

### Appendices & printable aids

- [Pi Carrier Field Guide](./pi_carrier_field_guide.md)
- [Pi Carrier Flowcharts](./pi_image_flowcharts.md)
- [Pi Carrier QR Labels](./pi_carrier_qr_labels.md)
- [Pi Boot & Cluster Troubleshooting Matrix](./pi_boot_troubleshooting.md)
- [Pi Image Contributor Guide](./pi_image_contributor_guide.md)
- [Pi Support Bundles](./pi_support_bundles.md)
- [Pi Image Quickstart](./pi_image_quickstart.md)

## Changelog & ownership

- Created: merged guidance from quickstart, builder design, provisioning, and
  troubleshooting docs into a unified launch playbook.
- Owners: Pi image maintainers (`@futuroptimist/sugarkube-maintainers`). Update
  this file alongside any change to flashing scripts, provisioning units, or
  post-boot automation so downstream PDFs and QR codes stay in sync.
