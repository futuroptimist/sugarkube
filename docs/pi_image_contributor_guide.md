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
  - Related tooling: referenced by the planned `first-boot.service`, included in `/boot/first-boot-
    report.txt`, and validated by the Bats tests in `tests/pi_node_verifier_*.bats`.
- `scripts/publish_telemetry.py`
  - Purpose: run `pi_node_verifier`, hash device fingerprints, and publish anonymized telemetry to a
    configurable endpoint.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Telemetry Hooks](./pi_image_telemetry.md).
  - Related tooling: exposed via `make publish-telemetry`, `just publish-telemetry`, and the
    `sugarkube-telemetry.timer` service defined in cloud-init.
- `scripts/pi_smoke_test.py`
  - Purpose: orchestrate remote verifier runs over SSH, optionally rebooting hosts to confirm
    convergence and emitting JSON for CI harnesses.
  - Primary docs: [Pi Image Quickstart](./pi_image_quickstart.md),
    [Pi Image Smoke Test Harness](./pi_smoke_test.md).
  - Related tooling: wrapped by `make smoke-test-pi` and `just smoke-test-pi` so operators can pass
    flags through `SMOKE_ARGS` without remembering the Python entry point.
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
- `scripts/cloud-init/export-kubeconfig.sh`, `scripts/cloud-init/export-node-token.sh`, and friends under `scripts/cloud-init/`
  - Purpose: capture sanitized/full kubeconfigs, mirror the k3s node token, start token.place/dspace projects, and log provisioning milestones
    for inclusion in `/boot/first-boot-report.txt`.
  - Primary docs: [Pi Headless Provisioning](./pi_headless_provisioning.md),
    [Pi Token + dspace](./pi_token_dspace.md).

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
