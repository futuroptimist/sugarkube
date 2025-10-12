---
personas:
  - software
---

# Sugarkube Automation Script Map

Keep documentation and tooling changes aligned by using this reference when updating
scripts or guides. Each table row links a helper to the documentation that introduces it,
plus any supporting automation. After editing a script or doc, rerun the docs checks to
confirm the quickstart stays accurate.

> **Note:** The unified CLI forces helpers to run from the repository root so relative
> paths stay stable even when you invoke it from nested directories. Use the CLI entries
> below when you want consistent automation regardless of your current working directory.
> You can also run `python -m sugarkube_toolkit ...` from the repository root for direct
> imports, or call `./scripts/sugarkube ...` (or add `scripts/` to your `PATH`) to let the
> wrapper bootstrap `PYTHONPATH` automatically. The reminder is enforced by
> `tests/test_cli_docs_repo_root.py`, which uses `monkeypatch.chdir` to enter nested folders
> before invoking `docs verify` and `docs simplify` so the documentation stays aligned.
> Prefer [go-task](https://taskfile.dev)? `Taskfile.yml` mirrors these helpers with namespaced
> entries such as `task docs:verify` and `task pi:download` so contributors can stick to a
> single task runner.

## Image download and install helpers

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/download_pi_image.sh` | Resolve the latest release, resume partial downloads, and verify checksums/signatures. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | `Makefile` `download-pi-image` / `just download-pi-image` targets |
| `scripts/sugarkube-latest` | Convenience wrapper that defaults to release downloads. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | Works with the same flags as `download_pi_image.sh`. |
| `scripts/install_sugarkube_image.sh` | One-line installer that bootstraps `gh`, downloads, verifies, and expands the latest release (`--dry-run` prints the planned steps). | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | `Makefile` `install-pi-image`, `just install-pi-image`, curl one-liner |
| `scripts/collect_pi_image.sh` | Normalize pi-gen output, clean staging directories, and compress images for release. | [Pi Image Builder Design](./pi_image_builder_design.md) | Used inside GitHub Actions and local builds via `make build-pi-image`. |
| `scripts/build_pi_image.sh` | Build the Raspberry Pi OS image with cloud-init, k3s, and bundled repos. | [Pi Image Builder Design](./pi_image_builder_design.md) | Called by `Makefile`/`just` build targets and the pi-image workflow. |

## Flashing and reporting helpers

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/flash_pi_media.sh` | Stream `.img`/`.img.xz` to removable media with checksum verification and auto-eject. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | `Makefile`/`just` `flash-pi` targets, PowerShell wrapper |
| `scripts/flash_pi_media.py` | Cross-platform core used by Bash and PowerShell wrappers. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | Imported by `flash_pi_media.sh` and `flash_pi_media.ps1`. |
| `scripts/flash_pi_media_report.py` | Generate Markdown/HTML/JSON flash reports with optional cloud-init diffs. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | `make flash-pi-report`, `just flash-pi-report`, report templates under `~/sugarkube/reports/`. |
| `scripts/pi_cluster_bootstrap.py` | Trigger the `pi-image` workflow, download artifacts, flash media, and run join rehearsals from a single TOML config. | [Raspberry Pi Cluster Setup](./raspi_cluster_setup.md) §Fast path | `python -m sugarkube_toolkit pi cluster`, `make cluster-bootstrap`, `just cluster-bootstrap` |
| `scripts/render_pi_imager_preset.py` | Merge secrets into Raspberry Pi Imager presets. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | Works with presets in `docs/templates/pi-imager/`. |

## Boot verification and troubleshooting

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/pi_node_verifier.sh` | Validate k3s readiness, token.place/dspace health, and record results in `/boot/first-boot-report/summary.*`. | [Pi Image Quickstart](./pi_image_quickstart.md) §3, [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md) | Invoked during image builds, `first_boot_service.py`, and via `make doctor`/`just doctor`. |
| `scripts/first_boot_service.py` + `scripts/systemd/first-boot.service` | Automate rootfs expansion, wait for cloud-init, run the verifier with retries, and publish Markdown/HTML/JSON reports plus markers under `/boot/first-boot-report/`. | [Pi Image Quickstart](./pi_image_quickstart.md) §3, [Pi Headless Provisioning](./pi_headless_provisioning.md), [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md) | Bundled during image builds, enabled on first boot, tested by `tests/first_boot_service_test.py`. |
| `scripts/pi_smoke_test.py` | Run `pi_node_verifier.sh` over SSH, optionally rebooting nodes to confirm convergence. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Run remote smoke tests", [Pi Image Smoke Test Harness](./pi_smoke_test.md) | `make smoke-test-pi`, `just smoke-test-pi` |
| `scripts/pi_multi_node_join_rehearsal.py` | Rehearse scaling by fetching the k3s join secret, printing commands, and running agent SSH preflights. | [Pi Multi-Node Join Rehearsal](./pi_multi_node_join_rehearsal.md) | `make rehearse-join`, `just rehearse-join` |
| `scripts/update_hardware_boot_badge.py` | Generate the shields.io endpoint JSON for hardware boot badge updates. | [Pi Image Contributor Guide](./pi_image_contributor_guide.md) §"Record hardware boot runs" | `make update-hardware-badge`, `just update-hardware-badge`, README status badge |
| `scripts/cloud-init/export-kubeconfig.sh` | Export sanitized and full kubeconfigs to `/boot/sugarkube-kubeconfig*`. | [Pi Image Quickstart](./pi_image_quickstart.md) §3 | Runs from cloud-init during first boot. |
| `scripts/cloud-init/export-node-token.sh` | Mirror the k3s node token to `/boot/sugarkube-node-token` for recovery joins.<br>Systemd path units rerun it automatically when the source token appears. | [Pi Image Quickstart](./pi_image_quickstart.md) §3 | Runs from cloud-init during first boot. |
| `scripts/cloud-init/apply-helm-bundles.sh` | Apply pinned Helm releases once k3s is Ready and record Markdown reports under `/boot/first-boot-report/helm-bundles/`. | [Pi Image Quickstart](./pi_image_quickstart.md) §3, [Sugarkube Helm Bundle Hooks](./pi_helm_bundles.md) | Triggered by `sugarkube-helm-bundles.service` with self-heal escalation on failure. |
| `scripts/cloud-init/start-projects.sh` | Launch bundled projects and log migration events for the verifier. | [Pi Image Quickstart](./pi_image_quickstart.md) §3 | Triggered by cloud-init service units. |
| `scripts/sugarkube_doctor.sh` | Chain download dry-runs, flash validation, and linting checks. | [README](../README.md) `make doctor` section | Wrapped by `make doctor` / `just doctor` and the unified CLI. |
| `scripts/rollback_to_sd.sh` | Restore `/boot/cmdline.txt` and `/etc/fstab` after SSD issues, emitting Markdown reports. | [SSD Recovery and Rollback](./ssd_recovery.md) | Referenced by Makefile/justfile shortcuts. |

## SSD validation and monitoring

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/ssd_clone.py` | Clone the active SD card with dry-run previews, auto-target selection, and resumable steps. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Automatic SSD cloning" | `make clone-ssd`, `just clone-ssd` |
| `scripts/ssd_clone_service.py` + `scripts/systemd/ssd-clone.service` | Wait for a hot-plugged SSD, invoke the clone helper, and stop once `/var/log/sugarkube/ssd-clone.done` exists. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Automatic SSD cloning" | Bundled in pi image builds, triggered by the udev helper (not enabled at boot) |
| `scripts/ssd_post_clone_validate.py` | Validate cloned SSDs, compare boot config, and run stress tests. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Validate SSD clones", [SSD Post-Clone Validation](./ssd_post_clone_validation.md) | `make validate-ssd-clone`, `just validate-ssd-clone` |
| `scripts/ssd_health_monitor.py` | Collect SMART metrics, temperatures, and wear indicators with optional reporting. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Monitor SSD health", [SSD Health Monitor](./ssd_health_monitor.md) | `make monitor-ssd-health`, `just monitor-ssd-health` |

## Printable references

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/render_field_guide_pdf.py` | Build the one-page Pi carrier field guide PDF without extra dependencies. | [Pi Carrier Field Guide](./pi_carrier_field_guide.md), [Pi Image Quickstart](./pi_image_quickstart.md) | `make field-guide`, `just field-guide` |

## Unified CLI wrappers

| Command | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `python -m sugarkube_toolkit docs verify [--dry-run]` | Run `pyspelling` and `linkchecker` together, mirroring the contribution workflow expectations. | [simplification_suggestions.md](../simplification_suggestions.md) §1 | `scripts/toolkit/` shared runner, `tests/test_sugarkube_toolkit_cli.py` |
| `python -m sugarkube_toolkit docs simplify [--dry-run] [-- args...]` | Install docs prerequisites and run `scripts/checks.sh --docs-only` without leaving the CLI. | [simplification_suggestions.md](../simplification_suggestions.md) §1, [README.md](../README.md) §"Getting Started" | `scripts/checks.sh`, `tests/test_sugarkube_toolkit_cli.py::test_docs_simplify_invokes_checks_helper` |
| `python -m sugarkube_toolkit docs start-here [--path-only]` | Surface the Start Here handbook path or contents from any directory. | [docs/start-here.md](./start-here.md) | `docs/start-here.md`, `tests/test_sugarkube_toolkit_cli.py::test_docs_start_here_prints_path_only` |
| `python -m sugarkube_toolkit doctor [--dry-run] [-- args...]` | Run the end-to-end `sugarkube_doctor.sh` workflow without memorizing the legacy path. | [README.md](../README.md) §"Pi image releases" | `scripts/sugarkube_doctor.sh`, `tests/test_sugarkube_toolkit_cli.py::test_doctor_invokes_helper` |
| `python -m sugarkube_toolkit pi download [--dry-run] [args...]` | Download the latest release via `scripts/download_pi_image.sh` without leaving the unified CLI. `--dry-run` forwards to the shell helper so the preview matches running it directly. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | `scripts/download_pi_image.sh`, `tests/test_sugarkube_toolkit_cli.py` |
| `python -m sugarkube_toolkit pi install [--dry-run] [-- args...]` | Download and expand the latest release via `scripts/install_sugarkube_image.sh`. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | `scripts/install_sugarkube_image.sh`, `tests/test_sugarkube_toolkit_cli.py::test_pi_install_invokes_helper`, `tests/test_sugarkube_toolkit_cli.py::test_pi_install_respects_existing_dry_run` |
| `python -m sugarkube_toolkit pi flash [--dry-run] [args...]` | Flash removable media via `scripts/flash_pi_media.sh` with the same CLI used for downloads. The CLI forwards `--dry-run` so previews validate devices and checksums without writing bytes. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | `scripts/flash_pi_media.sh`, `tests/test_sugarkube_toolkit_cli.py::test_pi_flash_invokes_helper`, `tests/test_sugarkube_toolkit_cli.py::test_pi_flash_forwards_additional_args`, `tests/test_sugarkube_toolkit_cli.py::test_pi_flash_respects_existing_dry_run` |
| `python -m sugarkube_toolkit pi report [--dry-run] [args...]` | Generate flash reports via `scripts/flash_pi_media_report.py` without leaving the unified CLI. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | `scripts/flash_pi_media_report.py`, `tests/test_sugarkube_toolkit_cli.py::test_pi_report_invokes_helper`, `tests/test_sugarkube_toolkit_cli.py::test_pi_report_appends_cli_dry_run_with_separator` |
| `python -m sugarkube_toolkit pi rehearse [--dry-run] [args...]` | Rehearse multi-node joins via `scripts/pi_multi_node_join_rehearsal.py` without leaving the unified CLI. | [Pi Multi-Node Join Rehearsal](./pi_multi_node_join_rehearsal.md) | `scripts/pi_multi_node_join_rehearsal.py`, `tests/test_sugarkube_toolkit_cli.py::test_pi_rehearse_invokes_helper` |
| `python -m sugarkube_toolkit pi support-bundle [--dry-run] [args...]` | Collect Sugarkube diagnostics via `scripts/collect_support_bundle.py` without leaving the unified CLI. `--dry-run` prints the invocation for review instead of executing the helper. | [Pi Support Bundles](./pi_support_bundles.md) | `scripts/collect_support_bundle.py`, `tests/test_sugarkube_toolkit_cli.py::test_pi_support_bundle_invokes_helper`, `tests/test_sugarkube_toolkit_cli.py::test_pi_support_bundle_filters_helper_dry_run_flag` |

## Keeping docs and automation in sync

- Update both the script *and* its corresponding guide when behaviour changes.
- Run `pyspelling -c .spellcheck.yaml` and `linkchecker --no-warnings README.md docs/` to
  catch outdated references before you push.
- When adding new helpers, extend this map and cross-link the relevant guide sections so
  operators see the new workflow immediately.
