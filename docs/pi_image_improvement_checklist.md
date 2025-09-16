# Pi Image UX & Automation Improvement Checklist

The `pi_carrier` cluster should feel "plug in and go." Use this list to guide
upgrades that reduce manual work and ensure anyone can confidently boot a Pi,
clone the SD card to SSD, and land in a healthy k3s cluster with `tokenplace`
and `dspace` running.

## Documentation polish
- [ ] Merge `pi_image_quickstart.md`, `pi_image_builder_design.md`, and
  `raspi_cluster_setup.md` into a single end-to-end guide with a 10-minute
  "fast path" followed by deeper reference sections.
- [ ] Embed an animated GIF (or short video) that shows downloading the artifact,
  flashing with Raspberry Pi Imager, and confirming first boot so hesitant users
  can visually follow along.
- [ ] Add a printable one-page "field guide" (PDF) with the exact commands,
  default credentials, and LED/status expectations for the first boot.
- [ ] Expand troubleshooting tables that map LED patterns, `journalctl`
  messages, and `kubectl` errors to likely fixes.
- [ ] Document SSD cloning with both `rpi-clone` and `raspi-config`'s USB boot
  flow, highlighting how to verify UUID updates.
- [ ] Provide a checklist for prepping multiple Pis simultaneously (labeling
  media, staggering boots, verifying k3s tokens).

## Automation & tooling
- [ ] Publish an `imagectl` helper script that wraps
  `scripts/download_pi_image.sh`, verifies the checksum, and launches Raspberry
  Pi Imager in unattended mode via its CLI.
- [ ] Add an `sd-flash` GitHub Action that writes the artifact to removable
  media on a self-hosted runner for fleet provisioning days.
- [ ] Ship a `first-boot.service` that waits for the network, expands the
  filesystem, and emits a structured JSON status file to `/var/log/sugarkube/`
  for later auditing.
- [ ] Bundle a `post-flash` script that auto-configures Wi-Fi, SSH keys, and
  hostname based on a YAML manifest checked into the repo.
- [ ] Automate SSD cloning with an idempotent systemd service that:
  1. Detects the target NVMe/SATA device.
  2. Runs `sgdisk --replicate` and `rsync --info=progress2` to mirror the SD.
  3. Updates `/boot/cmdline.txt` and `/etc/fstab` to the SSD UUID.
  4. Touches `/var/log/sugarkube/ssd-clone.done` so the service runs only once.
- [ ] Add a `k3s-ready.target` that depends on `projects-compose.service` and a
  health-check script confirming `kubectl get nodes` returns `Ready`.

## Testing & verification
- [ ] Extend the pi-image workflow to boot the artifact in QEMU, run smoke tests
  (k3s status, `tokenplace` and `dspace` container health), and upload logs when
  failures occur.
- [ ] Add contract tests for `projects-compose.service` that assert required
  ports are open and HTTP health endpoints respond within 30 seconds.
- [ ] Build a hardware-in-the-loop test bench: USB-controlled PDU, HDMI capture,
  and serial console that boots a physical Pi on each release and archives
  telemetry.
- [ ] Publish a conformance badge in the README that shows the last successful
  hardware boot test and commit hash.
- [ ] Capture `kubectl get events`, `helm list`, and `systemd-analyze blame`
  outputs as artifacts for every pipeline run to accelerate triage.

## User experience refinements
- [ ] Create a web UI (served from `docs/` via GitHub Pages) where users paste a
  workflow run URL and receive direct download links plus flashing instructions
  tailored to their OS.
- [ ] Offer a `brew install sugarkube` tap that ships the helper scripts and a
  `sugarkube setup` interactive wizard for macOS users.
- [ ] Package a cross-platform desktop notifier that watches the workflow run
  and prompts users when the artifact is ready to flash.
- [ ] Add QR codes on the physical `pi_carrier` pointing to the quickstart and
  troubleshooting docs.
- [ ] Print the cluster token and default kubeconfig to `/boot/` so users can
  grab them without SSH if something stalls during first boot.
- [ ] Provide an optional `sugarkube-teams` webhook that posts boot/clone
  progress to Slack or Matrix for remote monitoring.

Track progress directly in PR descriptions so contributors can tick items as
they land. When the final checkboxes are complete the Pi experience should feel
as sweet as the sugarkube name promises.
