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
- [x] Install `first-boot.service` that:
  - Waits for network, expands filesystem.
  - Runs `pi_node_verifier.sh` automatically.
  - Publishes HTML/JSON status (cloud-init, k3s, token.place, dspace) to `/boot/first-boot-report`.
  - Implemented via `first_boot_service.py` and `first-boot.service` which expand the
    rootfs when needed, capture cloud-init status, retry the verifier, and publish
    Markdown/HTML/JSON summaries plus success markers under `/boot/first-boot-report/`.
- [x] Log verifier results and migration steps to `/boot/first-boot-report.txt`.
  - `pi_node_verifier.sh` now writes Markdown summaries (hardware, cloud-init,
    checksum checks) to `/boot/first-boot-report.txt` and ingests migration
    events recorded by `scripts/cloud-init/start-projects.sh`.
- [x] Add self-healing units that retry container pulls, rerun `cloud-init clean`, or reboot into maintenance with actionable logs.
  - Added `sugarkube-self-heal@.service` and `self_heal_service.py`, which retry Docker Compose pulls,
    restart failed units, clean `cloud-init`, capture journals under `/boot/first-boot-report/self-heal/`,
    and escalate to `rescue.target` after repeated failures.
- [x] Provide optional telemetry hooks to publish anonymized health data to a shared dashboard.
  - Added `sugarkube-publish-telemetry`, cloud-init environment/service templates, Makefile/just
    wrappers, and docs covering opt-in uploads to custom collectors.

---

## SSD Migration & Storage Hardening
- [x] Automate SSD cloning via `ssd-clone.service` or `pi-clone.service`:
  - Detect attached SSD.
  - Replicate partition table (`sgdisk --replicate` or `ddrescue`).
  - `rsync --info=progress2` SD → SSD.
  - Update `/boot/cmdline.txt` and `/etc/fstab` with new UUID.
  - Touch `/var/log/sugarkube/ssd-clone.done`.
  - Implemented via `scripts/ssd_clone_service.py`, `scripts/systemd/ssd-clone.service`, and a
    udev rule that starts the helper whenever a USB/NVMe disk appears. The service auto-selects the
    target disk, resumes partial runs, respects manual overrides, and installs alongside
    `ssd_clone.py` during image builds without enabling the unit at boot (so multi-user.target is not
    delayed when no SSD is attached).
- [x] Support dry-run + resume for cloning to reduce user hesitation.
  - Added `scripts/ssd_clone.py` plus Makefile/justfile wrappers that replicate partitions,
    support `--dry-run` previews, persist state, and resume clones via `--resume`.
- [x] Provide post-clone validation: EEPROM boot order, fstab UUIDs, read/write stress tests.
  - Added `scripts/ssd_post_clone_validate.py` plus Makefile/just wrappers. The helper compares live
    mounts with `/etc/fstab`, `/boot/cmdline.txt`, and EEPROM boot order, then runs a configurable
    SSD stress test with Markdown/JSON reports under `~/sugarkube/reports/ssd-validation/`.
- [x] Publish a recovery guide and rollback script to fall back to SD if SSD checks fail.
  - Added `scripts/rollback_to_sd.sh` plus Makefile/just wrappers, and documented the
    workflow in `docs/ssd_recovery.md` with dry-run guidance and report expectations.
- [x] Offer an opt-in SSD health monitor (SMART/wear checks).
  - Added `scripts/ssd_health_monitor.py`, Makefile/just wrappers, and
    [`SSD Health Monitor`](./ssd_health_monitor.md) docs covering manual runs and an optional
    systemd timer for recurring SMART snapshots.

---

## k3s, token.place & dspace Reliability
- [x] Add a `k3s-ready.target` that depends on `projects-compose.service`.
  - The target only completes once `kubectl get nodes` reports `Ready`.
  - Added `k3s-ready.target`/`k3s-ready.service` plus a readiness script that runs `kubectl wait` before
    marking the target reached, with cloud-init wiring and docs for chaining workloads.
- [x] Extend verifier to ensure:
  - k3s node is `Ready`.
  - `projects-compose.service` is active.
  - `token.place` and `dspace` endpoints respond on HTTPS/GraphQL.
  - `scripts/pi_node_verifier.sh` now discovers a kubeconfig, runs `kubectl get nodes`,
    checks `projects-compose.service`, and probes token.place/dspace HTTP(S)/GraphQL
    endpoints with configurable URLs/TLS flags so reports surface regressions
    automatically.
- [x] Provide post-boot hooks that apply pinned Helm/chart bundles and fail fast with logs if health checks fail.
  - Added `scripts/cloud-init/apply-helm-bundles.sh` plus `sugarkube-helm-bundles.service` to
    install Helm, read `/etc/sugarkube/helm-bundles.d/*.env`, run `helm upgrade --install --atomic`,
    and bail out through the self-heal unit when rollouts or health probes fail. Markdown reports
    now land under `/boot/first-boot-report/helm-bundles/` for air-gapped debugging, and the
    workflow is documented in [Sugarkube Helm Bundle Hooks](./pi_helm_bundles.md).
- [x] Bundle sample datasets and token.place collections for first-launch validation.
  - Added `samples/token_place/` plus a replay helper that the image copies into
    `/opt/sugarkube/` and `/opt/projects/token.place/` so first boot can confirm
    health, model listings, and chat completions with a single command.
- [x] Document and script multi-node join rehearsal for scaling clusters.
  - Added `scripts/pi_multi_node_join_rehearsal.py`, `make rehearse-join`/`just rehearse-join`
    wrappers, and the [Pi Multi-Node Join Rehearsal](./pi_multi_node_join_rehearsal.md) guide to
    walk operators through join-secret retrieval and agent preflight checks.
- [x] Store kubeconfig (sanitized) in `/boot/sugarkube-kubeconfig` for retrieval without SSH.
  - Added `scripts/cloud-init/export-kubeconfig.sh`, installed during image builds and invoked by
    cloud-init to export a redacted kubeconfig and log its status. Documentation now references
    the `/boot/sugarkube-kubeconfig` handoff path for quick operator access.
- [x] Bundle lightweight exporters (Grafana Agent/Netdata/Prometheus) pre-configured for cluster observability.

---

## Testing & CI Hardening
- [x] Extend pi-image workflow with QEMU smoke tests that boot the image, wait for cloud-init, run verifier, and upload logs.
  - `scripts/qemu_pi_smoke_test.py` now prepares the built image for virtualization, boots it via
    `qemu-system-aarch64`, watches the serial console for `[first-boot]` success messages, and copies
    `/boot/first-boot-report/` plus `/var/log/sugarkube/` into CI artifacts. The job runs after each
    release build and the Makefile/Just targets expose the same harness locally.
- [x] Add contract tests asserting ports are open, health endpoints respond, and container digests remain pinned.
  - Added `tests/projects_compose_contract_test.py` to enforce token.place/dspace port exposure,
    ensure observability images stay pinned to known SHA-256 digests, and expanded the Bats suite to
    require passing HTTP health probes before merging.
- [x] Integrate spellcheck/linkcheck gating (`pyspelling`, `linkchecker`) for docs.
- [ ] Build hardware-in-the-loop test bench: USB PDU, HDMI capture, serial console, boot physical Pis, archive telemetry.
- [x] Provide smoke-test harnesses (Ansible or shell) that SSH into fresh Pis, check k3s readiness, app health, and cluster convergence after reboots.
  - Added `scripts/pi_smoke_test.py` plus Makefile/just wrappers so operators can run
    verifier checks over SSH, optionally rebooting hosts to confirm convergence and
    emitting JSON summaries for CI pipelines.
- [x] Capture support bundles (`kubectl get events`, `helm list`, `systemd-analyze blame`, Compose logs, journal slices) for every pipeline run.
  - Added `scripts/collect_support_bundle.py` plus `make`/`just support-bundle` wrappers and wired
    the release workflow to archive bundles (documented in [Pi Support Bundles](./pi_support_bundles.md)).
- [x] Document how to run integration tests locally via `act`.
  - `docs/pi_image_builder_design.md` now includes a quick recipe for dry-running the release workflow with `act`.
- [x] Publish a conformance badge in the README showing last successful hardware boot.

---

## Documentation & Onboarding
- [x] Merge fragmented docs (`pi_image_quickstart.md`, `pi_image_builder_design.md`, `pi_image_cloudflare.md`, `raspi_cluster_setup.md`, etc.) into a single end-to-end “Pi Carrier Launch Playbook.”
  - Added [Pi Carrier Launch Playbook](./pi_carrier_launch_playbook.md) and linked it from the
    quickstart and README.
- [x] Structure guide with:
  - A 10-minute fast path.
  - Persona-based walkthroughs (solo builder, classroom, maintainer).
  - Deep reference sections with wiring photos.
  - Implemented within the new playbook alongside cross-links back to detailed
    references.
- [x] Include a printable one-page field guide/checklist (PDF) with commands, expected outputs, LED/status reference, and troubleshooting links.
  - Added [Pi Carrier Field Guide](./pi_carrier_field_guide.md) with a companion PDF renderer
    (`scripts/render_field_guide_pdf.py`) plus quickstart/README links so a single sheet stays
    in sync with tooling expectations at the workbench.
- [ ] Embed GIFs, screencasts, or narrated clips showing download → flash → first boot → SSD clone → k3s readiness.
- [x] Provide start-to-finish flowcharts mapping the journey.
- [x] Expand troubleshooting tables linking LED patterns, journalctl logs, `kubectl` errors, and container health issues to fixes.
  - Added `docs/pi_boot_troubleshooting.md` plus quickstart references covering
    LED cues, critical commands, and recovery steps.
- [x] Publish contributor guide mapping automation scripts to docs; enforce sync with linkchecker and spellchecker.
  - Added [Pi Image Contributor Guide](./pi_image_contributor_guide.md) mapping automation helpers to their
    documentation and introduced `make docs-verify`/`just docs-verify` wrappers to run spellcheck and
    link-check together.

---

## Developer Experience & User Refinements
- [x] Provide `make doctor` / `just verify` that chains download, checksum, flash dry-run, and linting.
  - New `scripts/sugarkube_doctor.sh` chains dry-run downloads, flash validation, and optional lint
    plus link checks via `make doctor`.
- [x] Offer a `brew install sugarkube` tap and `sugarkube setup` wizard for macOS.
  - Added a Homebrew tap (`Formula/sugarkube.rb`), a `sugarkube-setup` CLI, and `make`/`just` targets
    that audit dependencies, seed configuration, and remind contributors to keep 100% patch coverage.
- [x] Package a cross-platform desktop notifier to alert when workflow artifacts are ready.
  - Added `scripts/workflow_artifact_notifier.py`, a GitHub CLI-backed poller exposed via
    `make notify-workflow` / `just notify-workflow` that posts native notifications on Linux, macOS,
    and Windows (with console fallbacks) when release artifacts finish uploading. Documented in
    [Sugarkube Workflow Artifact Notifications](./pi_workflow_notifications.md) with 100% patch
    coverage guaranteed by `tests/test_workflow_artifact_notifier.py`.
- [x] Serve a web UI (via GitHub Pages) where users paste a workflow URL and get direct flashing instructions tailored to OS.
  - Added [Sugarkube Flash Helper](./flash-helper/) plus `scripts/workflow_flash_instructions.py`
    so operators can generate identical guidance from the CLI or the published page.
- [x] Add QR codes on physical `pi_carrier` hardware pointing to quickstart and troubleshooting docs.
  - `scripts/generate_qr_codes.py` now exports SVG stickers plus a manifest, and
    `make qr-codes`/`just qr-codes` regenerate them. `docs/pi_carrier_qr_labels.md`
    covers printing and placement so every enclosure ships with quickstart and
    troubleshooting links.
- [x] Print cluster token and default kubeconfig to `/boot/` for recovery if first boot stalls.
- [x] Provide optional `sugarkube-teams` webhook that posts boot/clone progress to Slack or Matrix for remote monitoring.
  - Added `scripts/sugarkube_teams.py`, systemd integrations in `first_boot_service.py` and
    `ssd_clone_service.py`, a `/usr/local/bin/sugarkube-teams` CLI, Makefile/justfile wrappers, and
    the [Sugarkube Team Notifications](./pi_image_team_notifications.md) guide covering Slack/Matrix
    setup and troubleshooting.

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
