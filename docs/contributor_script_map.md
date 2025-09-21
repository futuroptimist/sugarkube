# Sugarkube Automation Script Map

Keep documentation and tooling changes aligned by using this reference when updating
scripts or guides. Each table row links a helper to the documentation that introduces it,
plus any supporting automation. After editing a script or doc, rerun the docs checks to
confirm the quickstart stays accurate.

## Image download and install helpers

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/download_pi_image.sh` | Resolve the latest release, resume partial downloads, and verify checksums/signatures. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | `Makefile` `download-pi-image` / `just download-pi-image` targets |
| `scripts/sugarkube-latest` | Convenience wrapper that defaults to release downloads. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | Works with the same flags as `download_pi_image.sh`. |
| `scripts/install_sugarkube_image.sh` | One-line installer that bootstraps `gh`, downloads, verifies, and expands the latest release. | [Pi Image Quickstart](./pi_image_quickstart.md) §1 | `Makefile` `install-pi-image`, `just install-pi-image`, curl one-liner |
| `scripts/collect_pi_image.sh` | Normalize pi-gen output, clean staging directories, and compress images for release. | [Pi Image Builder Design](./pi_image_builder_design.md) | Used inside GitHub Actions and local builds via `make build-pi-image`. |
| `scripts/build_pi_image.sh` | Build the Raspberry Pi OS image with cloud-init, k3s, and bundled repos. | [Pi Image Builder Design](./pi_image_builder_design.md) | Called by `Makefile`/`just` build targets and the pi-image workflow. |

## Flashing and reporting helpers

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/flash_pi_media.sh` | Stream `.img`/`.img.xz` to removable media with checksum verification and auto-eject. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | `Makefile`/`just` `flash-pi` targets, PowerShell wrapper |
| `scripts/flash_pi_media.py` | Cross-platform core used by Bash and PowerShell wrappers. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | Imported by `flash_pi_media.sh` and `flash_pi_media.ps1`. |
| `scripts/flash_pi_media_report.py` | Generate Markdown/HTML/JSON flash reports with optional cloud-init diffs. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | `make flash-pi-report`, `just flash-pi-report`, report templates under `~/sugarkube/reports/`. |
| `scripts/render_pi_imager_preset.py` | Merge secrets into Raspberry Pi Imager presets. | [Pi Image Quickstart](./pi_image_quickstart.md) §2 | Works with presets in `docs/templates/pi-imager/`. |

## Boot verification and troubleshooting

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/pi_node_verifier.sh` | Validate k3s readiness, token.place/dspace health, and record results in `/boot/first-boot-report.txt`. | [Pi Image Quickstart](./pi_image_quickstart.md) §3, [Pi Boot & Cluster Troubleshooting](./pi_boot_troubleshooting.md) | Invoked during image builds and via `make doctor`/`just doctor`. |
| `scripts/pi_smoke_test.py` | Run `pi_node_verifier.sh` over SSH, optionally rebooting nodes to confirm convergence. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Run remote smoke tests", [Pi Image Smoke Test Harness](./pi_smoke_test.md) | `make smoke-test-pi`, `just smoke-test-pi` |
| `scripts/cloud-init/export-kubeconfig.sh` | Export sanitized and full kubeconfigs to `/boot/sugarkube-kubeconfig*`. | [Pi Image Quickstart](./pi_image_quickstart.md) §3 | Runs from cloud-init during first boot. |
| `scripts/cloud-init/export-node-token.sh` | Mirror the k3s node token to `/boot/sugarkube-node-token` for recovery joins. | [Pi Image Quickstart](./pi_image_quickstart.md) §3 | Runs from cloud-init during first boot. |
| `scripts/cloud-init/start-projects.sh` | Launch bundled projects and log migration events for the verifier. | [Pi Image Quickstart](./pi_image_quickstart.md) §3 | Triggered by cloud-init service units. |
| `scripts/sugarkube_doctor.sh` | Chain download dry-runs, flash validation, and linting checks. | [README](../README.md) `make doctor` section | Wrapped by `make doctor` / `just doctor`. |
| `scripts/rollback_to_sd.sh` | Restore `/boot/cmdline.txt` and `/etc/fstab` after SSD issues, emitting Markdown reports. | [SSD Recovery and Rollback](./ssd_recovery.md) | Referenced by Makefile/justfile shortcuts. |

## SSD validation and monitoring

| Script | Purpose | Primary docs | Supporting automation |
| --- | --- | --- | --- |
| `scripts/ssd_post_clone_validate.py` | Validate cloned SSDs, compare boot config, and run stress tests. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Validate SSD clones", [SSD Post-Clone Validation](./ssd_post_clone_validation.md) | `make validate-ssd-clone`, `just validate-ssd-clone` |
| `scripts/ssd_health_monitor.py` | Collect SMART metrics, temperatures, and wear indicators with optional reporting. | [Pi Image Quickstart](./pi_image_quickstart.md) §"Monitor SSD health", [SSD Health Monitor](./ssd_health_monitor.md) | `make monitor-ssd-health`, `just monitor-ssd-health` |

## Keeping docs and automation in sync

- Update both the script *and* its corresponding guide when behaviour changes.
- Run `pyspelling -c .spellcheck.yaml` and `linkchecker --no-warnings README.md docs/` to
  catch outdated references before you push.
- When adding new helpers, extend this map and cross-link the relevant guide sections so
  operators see the new workflow immediately.
