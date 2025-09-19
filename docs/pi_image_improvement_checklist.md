# Pi Image UX & Automation Improvement Checklist

The `pi_carrier` cluster should feel "plug in and go." This checklist combines all ideas into a cohesive roadmap for reducing manual work so anyone can confidently boot a Pi, clone the SD card to SSD, and land in a healthy k3s cluster with **token.place** and **dspace** running.

---

## Release & Distribution Automation
- [x] Publish signed, versioned releases on every successful `main` merge, plus nightly rebuilds to keep dependencies fresh.
  - Implemented in `.github/workflows/pi-image-release.yml`, which builds on main merges and a daily schedule, then signs artifacts via cosign + GitHub OIDC.
- [x] Attach artifacts (`.img.xz`), checksums, and changelog snippets to GitHub Releases; include an “image availability” badge in `README.md` linking to the latest download and commit SHAs.
  - Releases now attach the image, checksum, metadata, manifest, signatures, and build log. `README.md` advertises availability with a Shields badge that points to the latest download.
- [x] Generate a machine-readable manifest (JSON/YAML) recording build inputs, git SHAs, and checksums for provenance verification. Cache pi-gen stage durations, verifier output, and commit IDs for reproducibility.
  - `scripts/create_build_metadata.py` captures pi-gen commits, stage durations, and build options; `scripts/generate_release_manifest.py` converts that into a provenance manifest and markdown notes, ready to store verifier output when available.
- [x] Extend `scripts/download_pi_image.sh` (or `grab_pi_image.sh`) to:
  - Resolve the latest release automatically.
  - Resume partial downloads.
  - Verify checksums/signatures.
  - Emit progress bars/ETAs.
  - Store artifacts under `~/sugarkube/images/` by default.
  - Implemented with resumable `curl` downloads, checksum verification, and a
    configurable default directory in `scripts/download_pi_image.sh`.
- [x] Provide a `sugarkube-latest` convenience wrapper for downloading + verifying in one step.
  - Added `scripts/sugarkube-latest`, which defaults to release downloads while
    still accepting all downloader flags.
- [x] Package a one-liner installer (`curl | bash`) that installs `gh` when missing, pulls the latest release, verifies checksums, and expands the image.
  - `scripts/install_sugarkube_image.sh` is safe to run via `curl | bash`; it bootstraps `gh`, downloads the release, verifies checksums, expands to `.img`, and writes a new `.img.sha256`.

---

## Flashing & Provisioning Automation
- [x] Ship cross-platform flashing helpers (`flash_pi_media.sh`, PowerShell twin, or CLI in Go/Rust/Node) that:
  - Discover SD/USB devices.
  - Stream `.img.xz` directly with progress (`xzcat | dd`).
  - Verify written bytes with SHA-256.
  - Auto-eject media.
  - Implemented via `scripts/flash_pi_media.py` with bash and PowerShell wrappers.
- [x] Ship Raspberry Pi Imager preset JSONs pre-filled with hostname, user, Wi-Fi, and SSH keys for load-and-go flashing.
  - Added `docs/templates/pi-imager/` presets plus
    `scripts/render_pi_imager_preset.py` to merge secrets and write Raspberry Pi
    Imager configuration snippets.
- [x] Provide `just`/`make` targets (e.g., `make flash-pi`) chaining download → verify → flash.
  - Added a root `Makefile` with `flash-pi`, `install-pi-image`, and `download-pi-image` targets that wrap the new installer and flashing helpers.
- [x] Bundle a wrapper script that auto-decompresses, flashes, verifies, and reports results in HTML/Markdown (hardware IDs, checksum results, cloud-init diff).
  - Added `scripts/flash_pi_media_report.py` plus `make flash-pi-report`/`just flash-pi-report`
    helpers that expand `.img.xz` releases, flash via the existing Python helper,
    capture checksum output, and emit Markdown/HTML reports with optional
    cloud-init diffs under `~/sugarkube/reports/`.
- [x] Document a headless provisioning path using `user-data` or `secrets.env` for injecting Wi-Fi/Cloudflare tokens without editing repo files.
  - Added `docs/pi_headless_provisioning.md` plus `docs/templates/cloud-init/user-data.example` for
    reusable `secrets.env` workflows and verifier integration.
- [x] Support Codespaces or `just` recipes to build and flash media with minimal local tooling.
  - Added a root `justfile` mirroring the Makefile helpers plus a `codespaces-bootstrap` target so
    Codespaces environments can install prerequisites and flash media using the same scripts.

---

## First Boot Confidence & Self-Healing
- [ ] Install `first-boot.service` that:
  - Waits for network, expands filesystem.
  - Runs `pi_node_verifier.sh` automatically.
  - Publishes HTML/JSON status (cloud-init, k3s, token.place, dspace) to `/boot/first-boot-report`.
- [x] Log verifier results and migration steps to `/boot/first-boot-report.txt`.
  - `pi_node_verifier.sh` now writes Markdown summaries (hardware, cloud-init,
    checksum checks) to `/boot/first-boot-report.txt` and ingests migration
    events recorded by `scripts/cloud-init/start-projects.sh`.
- [ ] Add self-healing units that retry container pulls, rerun `cloud-init clean`, or reboot into maintenance with actionable logs.
- [ ] Provide optional telemetry hooks to publish anonymized health data to a shared dashboard.

---

## SSD Migration & Storage Hardening
- [ ] Automate SSD cloning via `ssd-clone.service` or `pi-clone.service`:
  - Detect attached SSD.
  - Replicate partition table (`sgdisk --replicate` or `ddrescue`).
  - `rsync --info=progress2` SD → SSD.
  - Update `/boot/cmdline.txt` and `/etc/fstab` with new UUID.
  - Touch `/var/log/sugarkube/ssd-clone.done`.
- [ ] Support dry-run + resume for cloning to reduce user hesitation.
- [ ] Provide post-clone validation: EEPROM boot order, fstab UUIDs, read/write stress tests.
- [x] Publish a recovery guide and rollback script to fall back to SD if SSD checks fail.
  - Added `scripts/rollback_to_sd.sh` plus Makefile/just wrappers, and documented the
    workflow in `docs/ssd_recovery.md` with dry-run guidance and report expectations.
- [ ] Offer an opt-in SSD health monitor (SMART/wear checks).

---

## k3s, token.place & dspace Reliability
- [ ] Add a `k3s-ready.target` that depends on `projects-compose.service` and only completes when `kubectl get nodes` returns `Ready`.
- [ ] Extend verifier to ensure:
  - k3s node is `Ready`.
  - `projects-compose.service` is active.
  - `token.place` and `dspace` endpoints respond on HTTPS/GraphQL.
- [ ] Provide post-boot hooks that apply pinned Helm/chart bundles and fail fast with logs if health checks fail.
- [ ] Bundle sample datasets and token.place collections for first-launch validation.
- [ ] Document and script multi-node join rehearsal for scaling clusters.
- [ ] Store kubeconfig (sanitized) in `/boot/sugarkube-kubeconfig` for retrieval without SSH.
- [ ] Bundle lightweight exporters (Grafana Agent/Netdata/Prometheus) pre-configured for cluster observability.

---

## Testing & CI Hardening
- [ ] Extend pi-image workflow with QEMU smoke tests that boot the image, wait for cloud-init, run verifier, and upload logs.
- [ ] Add contract tests asserting ports are open, health endpoints respond, and container digests remain pinned.
- [x] Integrate spellcheck/linkcheck gating (`pyspelling`, `linkchecker`) for docs.
- [ ] Build hardware-in-the-loop test bench: USB PDU, HDMI capture, serial console, boot physical Pis, archive telemetry.
- [ ] Provide smoke-test harnesses (Ansible or shell) that SSH into fresh Pis, check k3s readiness, app health, and cluster convergence after reboots.
- [ ] Capture support bundles (`kubectl get events`, `helm list`, `systemd-analyze blame`, Compose logs, journal slices) for every pipeline run.
- [x] Document how to run integration tests locally via `act`.
  - `docs/pi_image_builder_design.md` now includes a quick recipe for dry-running the release workflow with `act`.
- [ ] Publish a conformance badge in the README showing last successful hardware boot.

---

## Documentation & Onboarding
- [ ] Merge fragmented docs (`pi_image_quickstart.md`, `pi_image_builder_design.md`, `pi_image_cloudflare.md`, `raspi_cluster_setup.md`, etc.) into a single end-to-end “Pi Carrier Launch Playbook.”
- [ ] Structure guide with:
  - A 10-minute fast path.
  - Persona-based walkthroughs (solo builder, classroom, maintainer).
  - Deep reference sections with wiring photos.
- [ ] Include a printable one-page field guide/checklist (PDF) with commands, expected outputs, LED/status reference, and troubleshooting links.
- [ ] Embed GIFs, screencasts, or narrated clips showing download → flash → first boot → SSD clone → k3s readiness.
- [ ] Provide start-to-finish flowcharts mapping the journey.
- [ ] Expand troubleshooting tables linking LED patterns, journalctl logs, `kubectl` errors, and container health issues to fixes.
- [ ] Publish contributor guide mapping automation scripts to docs; enforce sync with linkchecker and spellchecker.

---

## Developer Experience & User Refinements
- [x] Provide `make doctor` / `just verify` that chains download, checksum, flash dry-run, and linting.
  - New `scripts/sugarkube_doctor.sh` chains dry-run downloads, flash validation, and optional lint
    plus link checks via `make doctor`.
- [ ] Offer a `brew install sugarkube` tap and `sugarkube setup` wizard for macOS.
- [ ] Package a cross-platform desktop notifier to alert when workflow artifacts are ready.
- [ ] Serve a web UI (via GitHub Pages) where users paste a workflow URL and get direct flashing instructions tailored to OS.
- [ ] Add QR codes on physical `pi_carrier` hardware pointing to quickstart and troubleshooting docs.
- [ ] Print cluster token and default kubeconfig to `/boot/` for recovery if first boot stalls.
- [ ] Provide optional `sugarkube-teams` webhook that posts boot/clone progress to Slack or Matrix for remote monitoring.

---

## Troubleshooting & Community
- [ ] Ship a golden recovery console image or partition with CLI tools to reflash, fetch logs, and reinstall k3s without another machine.
- [x] Extend `outages/` with playbooks for scenarios like cloud-init hangs, SSD clone stalls, or projects-compose failures.
  - Added outage records for cloud-init stalls, SSD clone resumes, and projects-compose triage that
    point to the headless provisioning playbook.
- [x] Add an issue template asking contributors to reference this checklist so coverage gaps are visible.
  - Added `.github/ISSUE_TEMPLATE/pi-image.md` with prompts to link manifest data and tick the checklist sections touched.

---

Track progress directly in PR descriptions so contributors can tick items as they land. When the final checkboxes are complete, the Pi experience should feel as sweet as the sugarkube name promises.
