# Pi Carrier Launch Playbook

Launch a sugarkube cluster from zero to k3s workloads without hopping between guides.
This playbook stitches together the quickstart, provisioning, observability, and
troubleshooting docs so a single Markdown file carries you from download through
post-boot validation.

## How to use this playbook

- ✅ **Print or share it** before workshops so everyone follows the same sequence.
- ✅ **Keep a terminal open** and copy the commands block-by-block without skipping
  checksum or verification steps.
- ✅ **Expect 100% test coverage on the first run.** Every helper surfaces that
  requirement; the workflow sections below point to the exact commands to hit the
  expectation before merging changes.
- ✅ **Follow the persona walkthrough** that best matches your role, then dip into
  the deep reference sections when you need wiring diagrams, automation flags, or
  triage tips.

## 10-minute fast path

1. **Bootstrap your workstation.**
   ```bash
   brew tap sugarkube/sugarkube https://github.com/futuroptimist/sugarkube
   brew install sugarkube
   just mac-setup
   ```
   - On Linux or Windows, install [just](https://github.com/casey/just), `python3`,
     and `pipx`, then run `pipx install poetry` followed by
     `poetry install --with docs,test` to mirror CI toolchains.
2. **Download and expand the latest image.**
   ```bash
   curl -fsSL https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/install_sugarkube_image.sh | bash
   ```
   - Prefer local control? Run
     `./scripts/install_sugarkube_image.sh --dir ~/sugarkube/images`.
3. **Smoke-test in QEMU before touching hardware.**
   ```bash
   sudo make qemu-smoke QEMU_SMOKE_IMAGE=~/sugarkube/images/sugarkube.img.xz
   ```
   Inspect `artifacts/qemu-smoke/serial.log` for `[first-boot] SUCCESS`.
4. **Flash removable media with verification.**
   ```bash
   sudo ./scripts/flash_pi_media_report.py \
     --image ~/sugarkube/images/sugarkube.img.xz \
     --device /dev/sdX \
     --assume-yes
   ```
   The report lands under `~/sugarkube/reports/flash-*` with Markdown, HTML, and
   JSON copies.
5. **Boot and confirm services.**
   ```bash
   curl http://<pi-host>:9100/metrics
   curl http://<pi-host>:12345/metrics
   /opt/sugarkube/token_place_replay_samples.py
   ```
   Wrap up with `sudo kubectl get nodes` and
   `sudo systemctl status projects-compose.service` to ensure k3s and Compose are
   healthy.

## Persona walkthroughs

### Solo builder bringing one Pi online

1. Follow the **10-minute fast path** above.
2. Scan the [Pi Carrier Field Guide](./pi_carrier_field_guide.md) before powering the cube.
3. Stick the [QR labels](./pi_carrier_qr_labels.md) to the enclosure so future
   maintenance can jump straight to this playbook or the troubleshooting matrix.
4. After first boot, run
   ```bash
   sudo ./scripts/ssd_post_clone_validate.py --report ~/sugarkube/reports/ssd-validation
   ```
   to confirm migrations finish cleanly before trusting SSD storage.

### Classroom or lab facilitator provisioning multiple kits

1. Run the **10-minute fast path** once to prime caches under `~/sugarkube/`.
2. Generate Raspberry Pi Imager presets for each class member:
   ```bash
   python3 scripts/render_pi_imager_preset.py \
     --preset docs/templates/pi-imager/sugarkube-controller.preset.json \
     --secrets ~/sugarkube/secrets.env \
     --apply
   ```
3. Print the [field guide PDF](./pi_carrier_field_guide.pdf) and tape it to each
   station alongside the QR stickers.
4. Use `sudo make flash-pi FLASH_DEVICE=/dev/sdX` (or the `just` equivalent) to
   stream verified images to every card without juggling manual downloads.
5. Capture a support bundle after the class to archive telemetry:
   ```bash
   just support-bundle SUPPORT_BUNDLE_ARGS="--output ~/sugarkube/reports/class-$(date +%Y%m%d)"
   ```

### Maintainer shipping changes to automation or docs

1. Clone the repo and install contributors' tooling:
   ```bash
   git clone https://github.com/futuroptimist/sugarkube.git
   cd sugarkube
   poetry install --with docs,test
   pre-commit install
   ```
2. Stage edits, then run the full validation matrix once—**no retries**:
   ```bash
   pre-commit run --all-files
   pyspelling -c .spellcheck.yaml
   linkchecker --no-warnings README.md docs/
   pytest --cov --cov-fail-under=100
   git diff --cached | ./scripts/scan-secrets.py
   ```
3. Update manifests and docs referenced by your change, then tick the relevant
   checkbox in [pi_image_improvement_checklist.md](./pi_image_improvement_checklist.md).
4. Before merging, boot the image in QEMU and confirm CI artefacts upload cleanly.

## Deep reference

### Workspace, wiring, and enclosure resources

- [build_guide.md](./build_guide.md) — fabricate and assemble the cube.
- [electronics_basics.md](./electronics_basics.md) — wiring tools, safety, and best practices.
- [power_system_design.md](./power_system_design.md) — size batteries, controllers, and wiring gauges.
- [SAFETY.md](./SAFETY.md) — battery and panel safety.
- Share this wiring overview with contractors or electricians:

  ![Sugarkube wiring overview](./images/sugarkube_diagram.svg)

### Automation and observability at a glance

- [pi_image_quickstart.md](./pi_image_quickstart.md) — command-by-command detail behind the fast path.
- [pi_smoke_test.md](./pi_smoke_test.md) — SSH-based verification for physical hardware.
- [projects-compose.md](./projects-compose.md) — explains container layout, ports, and pinned digests.
- [pi_image_telemetry.md](./pi_image_telemetry.md) — opt-in telemetry collection and retention guidance.
- [pi_image_team_notifications.md](./pi_image_team_notifications.md) — Slack/Matrix hooks for remote status pings.
- [pi_support_bundles.md](./pi_support_bundles.md) — capture compose logs, systemd traces, and journal slices.

### Troubleshooting and recovery

- [pi_boot_troubleshooting.md](./pi_boot_troubleshooting.md) — LED codes, kubectl errors, and recovery steps.
- [ssd_post_clone_validation.md](./ssd_post_clone_validation.md) — post-migration health checks and stress tests.
- [pi_headless_provisioning.md](./pi_headless_provisioning.md) — preload Wi-Fi credentials and secrets via cloud-init.
- [outage_catalog.md](./outage_catalog.md) — incident retrospectives with remediation steps.
- [scripts/rollback_to_sd.sh](../scripts/rollback_to_sd.sh) — fall back to SD cards when SSD checks fail.

### Keep coverage green and audits happy

- All new code must ship with tests that keep **patch coverage at 100% on the first test run**.
- Use `pytest --cov --cov-fail-under=100` locally before opening a PR. CI matches this threshold.
- Run `git diff --cached | ./scripts/scan-secrets.py` every time to catch credentials before pushing.
- Tag follow-up work in [pi_image_improvement_checklist.md](./pi_image_improvement_checklist.md) so the roadmap stays honest.

## Next steps

Share feedback by opening an issue with screenshots or first-boot logs. Cite which playbook
section you followed so we can tighten the right automation path. When you enhance a workflow,
update this playbook alongside the supporting guides and aim for 100% coverage on the first
`pytest` run—no retries needed.
