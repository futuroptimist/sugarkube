# Pi Image Contributor Guide

This guide links every Pi image automation helper to the documentation that explains how to use it.
Use it when updating scripts or docs so releases, flashing workflows, and verifier reports stay in
sync.

## Keep docs and automation aligned

- Touching any file in `docs/` or `README.md`? Run the synchronized checks:
  ```bash
  make docs-verify
  # or
  just docs-verify
  ```
  Both commands execute `pyspelling -c .spellcheck.yaml` and
  `linkchecker --no-warnings README.md docs/` so every update keeps the documentation consistent
  with the automation helpers.
- Use `pre-commit run --all-files` to exercise `scripts/checks.sh`, which installs spellcheck and
  link-check dependencies automatically when missing.
- Ship changes with tests that deliver **100% patch coverage on the first `pytest` run**. Design
  tests before landing code so local runs (and CI) never require retries to close coverage gaps.
- When adding a new helper, update this mapping and reference it from the relevant guide so the
  quick-start and recovery docs stay authoritative.

## Automation map

### Download and release helpers

- `scripts/install_sugarkube_image.sh`
  - Purpose: one-line installer that resolves the latest release, verifies checksums, and expands
    the `.img.xz` locally.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Flowcharts](./pi_image_flowcharts.md).
  - Related tooling: exposed via `make install-pi-image`, `just install-pi-image`, and tested by
    `tests/install_sugarkube_image_test.py`.
- `scripts/download_pi_image.sh`
  - Purpose: resumable GitHub release downloads with checksum verification and progress output.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Builder Design](./pi_image_builder_design.md).
  - Related tooling: wrapped by `make download-pi-image`, `just download-pi-image`, and consumed by
    the installer script above.
- `scripts/collect_pi_image.sh`
  - Purpose: normalize pi-gen output and compress it into the release artifact layout.
  - Primary docs: [Pi Image Builder Design](./pi_image_builder_design.md).
  - Related tooling: invoked in the CI pipelines that publish release assets.
- `scripts/create_build_metadata.py` and `scripts/generate_release_manifest.py`
  - Purpose: capture build inputs, pi-gen SHAs, and stage timings, then export a signed manifest for
    releases.
  - Primary docs: [Pi Image Builder Design](./pi_image_builder_design.md).
  - Related tooling: referenced from the release workflow and validated by tests under
    `tests/test_create_build_metadata.py` and `tests/test_generate_release_manifest.py`.
- `scripts/sugarkube-latest`
  - Purpose: minimal wrapper for `download_pi_image.sh` when you only need the compressed artifact.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md).

### Flashing and reporting helpers

- `scripts/flash_pi_media.py`, `scripts/flash_pi_media.sh`, and `scripts/flash_pi_media.ps1`
  - Purpose: stream `.img` or `.img.xz` directly to removable media with checksum verification and
    automatic eject.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Flowcharts](./pi_image_flowcharts.md).
  - Related tooling: exercised by `make flash-pi`, `just flash-pi`, and the Windows wrapper to keep
    parity across platforms.
- `scripts/flash_pi_media_report.py`
  - Purpose: generate Markdown, HTML, and JSON flash reports that capture hardware IDs, checksum
    results, and optional cloud-init diffs.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md).
  - Related tooling: exposed through `make flash-pi-report`, `just flash-pi-report`, and archived by
    release consumers under `~/sugarkube/reports/`.
- `scripts/render_pi_imager_preset.py`
  - Purpose: merge secrets into Raspberry Pi Imager presets for headless provisioning.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Headless Provisioning](./pi_headless_provisioning.md).

### Verification and recovery helpers

- `scripts/pi_node_verifier.sh`
  - Purpose: verify k3s readiness, compose services, and token.place/dspace health during first
    boot.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md).
  - Related tooling: invoked by `first_boot_service.py`, included in `/boot/first-boot-
    report/summary.*`, and validated by the Bats tests in `tests/pi_node_verifier_*.bats`.
- `scripts/first_boot_service.py` + `scripts/systemd/first-boot.service`
  - Purpose: expand the rootfs, wait for cloud-init, run `pi_node_verifier.sh` with retries, and
    publish Markdown/HTML/JSON reports plus success markers under `/boot/first-boot-report/`.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Headless Provisioning](./pi_headless_provisioning.md),
    [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md).
  - Related tooling: bundled by `build_pi_image.sh`, enabled via systemd, and covered by
    `tests/first_boot_service_test.py`.
- `scripts/sugarkube_teams.py`
  - Purpose: publish Slack or Matrix notifications summarizing first boot verifier status and SSD
    clone milestones.
  - Primary docs: [Sugarkube Team Notifications](./pi_image_team_notifications.md).
  - Related tooling: imported by `first_boot_service.py` and `ssd_clone_service.py`, installed to
    `/opt/sugarkube/` with a `/usr/local/bin/sugarkube-teams` CLI, and surfaced through
    `make notify-teams` / `just notify-teams` wrappers.
- `scripts/workflow_artifact_notifier.py`
  - Purpose: watch GitHub Actions runs and raise desktop notifications when artifacts finish
    uploading, with console fallbacks when native notification binaries are missing.
  - Primary docs: [Sugarkube Workflow Artifact Notifications](./pi_workflow_notifications.md).
  - Related tooling: exposed via `make notify-workflow` / `just notify-workflow` and validated by
    `tests/test_workflow_artifact_notifier.py` to guarantee first-run patch coverage.
- `scripts/self_heal_service.py` + `sugarkube-self-heal@.service`
  - Purpose: respond to `projects-compose` and `cloud-init` failures by retrying Docker Compose pulls,
    running `cloud-init clean --logs`, and escalating to `rescue.target` with Markdown summaries under
    `/boot/first-boot-report/self-heal/`.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md),
    [projects-compose Service](./projects-compose.md).
  - Related tooling: installed by `build_pi_image.sh`, invoked via `OnFailure`, and validated by
    `tests/self_heal_service_test.py`.
- `scripts/pi_smoke_test.py`
  - Purpose: orchestrate remote verifier runs over SSH, optionally rebooting hosts to confirm
    convergence and emitting JSON for CI harnesses.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Smoke Test Harness](./pi_smoke_test.md).
  - Related tooling: wrapped by `make smoke-test-pi` and `just smoke-test-pi` so operators can pass
    flags through `SMOKE_ARGS` without remembering the Python entry point.
- `scripts/collect_support_bundle.py`
  - Purpose: collect Kubernetes, systemd, and Docker Compose diagnostics into a reusable
    support bundle for CI artifacts or manual triage.
  - Primary docs: [Pi Support Bundles](./pi_support_bundles.md),
    [Pi Image Quickstart](./pi_image_quickstart.md).
  - Related tooling: invoked via `make support-bundle` / `just support-bundle`, supports
    `SUPPORT_BUNDLE_ARGS` overrides, and publishes artifacts from `pi-image-release.yml` when
    bundle secrets are configured.
- `scripts/update_hardware_boot_badge.py`
  - Purpose: generate shields.io endpoint JSON so the README hardware boot badge reflects the
    latest physical verification run.
  - Primary docs: [Pi Image Contributor Guide](./pi_image_contributor_guide.md) §[Record hardware
    boot runs](#record-hardware-boot-runs).
  - Related tooling: exposed as `make update-hardware-badge` and `just update-hardware-badge` with a
    `BADGE_ARGS` passthrough for timestamp/notes.
- `scripts/sugarkube_doctor.sh`
  - Purpose: dry-run downloads, flash media in a synthetic environment, and optionally run
    repository linters.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Flowcharts](./pi_image_flowcharts.md).
  - Related tooling: executed via `make doctor` or `just doctor` and prints hints when `pyspelling`
    or `linkchecker` are missing locally.
- `scripts/rollback_to_sd.sh`
  - Purpose: undo SSD migrations by restoring `/boot/cmdline.txt` and `/etc/fstab` to SD defaults,
    writing a Markdown report alongside the boot partition.
  - Primary docs: [SSD Recovery and Rollback](./ssd_recovery.md).
  - Related tooling: surfaced as `make rollback-to-sd` and `just rollback-to-sd` helpers.
- `scripts/cloud-init/export-kubeconfig.sh`, `scripts/cloud-init/export-node-token.sh`,
  `scripts/cloud-init/apply-helm-bundles.sh`, and friends under `scripts/cloud-init/`
  - Purpose: capture sanitized/full kubeconfigs, mirror the k3s node token, apply
    pinned Helm bundles, start token.place/dspace projects, and log provisioning
    milestones for inclusion in `/boot/first-boot-report.txt`.
  - Primary docs: [Pi Headless Provisioning](./pi_headless_provisioning.md),
    [Pi Token + dspace](./pi_token_dspace.md), [Sugarkube Helm Bundle Hooks](./pi_helm_bundles.md).

#### Record hardware boot runs

Run the smoke test harness against real hardware after image releases or major changes, then update
the README badge so contributors know the last verified boot date:

```sh
just update-hardware-badge \
  BADGE_ARGS="--status pass --timestamp 2025-02-15T16:00:00Z --notes 'Pi 4B cluster'"
```

Key flags:

- `--status`: `pass`, `warn`, `fail`, or `unknown`; selects the badge colour and base label.
- `--timestamp`: ISO-8601 instant (UTC recommended). Use `now` to populate with the current time.
- `--notes`: short free-form annotation that appears after the timestamp (host, tester, etc.).
- `--description`: optional tooltip text for shields.io consumers.
- `--link`: hyperlink destination(s) for the badge. Supply once (or twice) to highlight reports.

The helper writes `docs/status/hardware-boot.json` and the README automatically renders the updated
badge via shields.io. Commit the refreshed JSON alongside your run notes so downstream operators can
trust the published status.

### Build workflows

- `scripts/build_pi_image.sh` and `scripts/build_pi_image.ps1`
  - Purpose: orchestrate pi-gen builds with cloud-init, token.place, and dspace baked into the
    image.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Builder Design](./pi_image_builder_design.md).
  - Related tooling: triggered manually via shell or by the GitHub Actions release workflow.
- `scripts/checks.sh`
  - Purpose: unify linting, spellcheck, link-check, CAD, and KiCad validations in CI and local
    development.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [README](../README.md), and [CONTRIBUTING](../CONTRIBUTING.md).
  - Related tooling: run via `pre-commit run --all-files` and from `scripts/sugarkube_doctor.sh`.

When you adjust any helper above, update the referenced docs and regenerate spellcheck/link-check via
`make docs-verify` to keep the automation story coherent for new contributors.
