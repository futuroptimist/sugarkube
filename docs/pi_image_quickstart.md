# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

Need a visual overview first? Start with the
[Pi Image Flowcharts](./pi_image_flowcharts.md) to map the journey from download to first boot
before diving into the commands below.

Maintainers updating scripts or docs should cross-reference the
[Pi Image Contributor Guide](./pi_image_contributor_guide.md) to keep automation helpers and
guidance aligned.

Need a hands-on reminder next to the hardware? Print the
[Pi carrier QR labels](./pi_carrier_qr_labels.md) and stick them to the enclosure so anyone can
scan straight to this quickstart or the troubleshooting matrix while standing at the workbench.

## 1. Build or download the image

1. Use the one-line installer to bootstrap everything in one step:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/install_sugarkube_image.sh | bash
   ```
   The script installs the GitHub CLI when missing, downloads the latest
   release, verifies the `.img.xz` checksum, expands it to
   `~/sugarkube/images/sugarkube.img`, and records a fresh `.img.sha256` hash.
   Pass `--download-only` to keep just the compressed archive or `--dir` to
   change the destination.
2. When working from a cloned repository, run the same helper locally:
   ```bash
   ./scripts/install_sugarkube_image.sh --dir ~/sugarkube/images --image ~/sugarkube/images/sugarkube.img
   ```
   All flags supported by `download_pi_image.sh` are forwarded, so `--release`
   and `--asset` continue to work. `./scripts/sugarkube-latest` remains
   available if you only need the compressed artifact.
3. In GitHub, open **Actions → pi-image → Run workflow** for a fresh build.
   - Tick **token.place** and **dspace** to bake those repos into `/opt/projects`.
   - Wait for the run to finish; it uploads `sugarkube.img.xz` as an artifact.
   - `./scripts/download_pi_image.sh --output /your/path.img.xz` still resumes
     partial downloads and verifies checksums automatically.
4. Alternatively, build on your machine:
   ```bash
   ./scripts/build_pi_image.sh
   ```
   Skip either project with `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`.
5. After any download or build, verify integrity:
   ```bash
   sha256sum -c path/to/sugarkube.img.xz.sha256
   ```
   The command prints `OK` when the checksum matches the downloaded image.

## 2. Flash the image
- Generate a self-contained report that expands `.img.xz`, flashes, verifies, and
  records the results:
  ```bash
  sudo ./scripts/flash_pi_media_report.py \
    --image ~/sugarkube/images/sugarkube.img.xz \
    --device /dev/sdX \
    --assume-yes \
    --cloud-init ~/sugarkube/cloud-init/user-data.yaml
  ```
  The wrapper stores Markdown/HTML/JSON logs under
  `~/sugarkube/reports/flash-*/flash-report.*`, capturing hardware IDs, checksum
  verification, and optional cloud-init diffs. Use
  ```bash
  sudo FLASH_DEVICE=/dev/sdX FLASH_REPORT_ARGS="--cloud-init ~/override.yaml" make flash-pi-report
  ```
  or the equivalent `just flash-pi-report` recipe to combine install → flash →
  report in one go.
- Stream the expanded image (or the `.img.xz`) directly to removable media:
  ```bash
  sudo ./scripts/flash_pi_media.sh --image ~/sugarkube/images/sugarkube.img --device /dev/sdX --assume-yes
  ```
  The helper auto-detects removable drives, streams `.img` or `.img.xz`
  without temporary files, verifies the written bytes with SHA-256, and
  powers the media off when complete. On Windows, run the PowerShell wrapper:
  ```powershell
  pwsh -File scripts/flash_pi_media.ps1 --image $env:USERPROFILE\sugarkube\images\sugarkube.img --device \\.\PhysicalDrive1
  ```
- To combine download + verify + flash in one command, run from the repo root:
  ```bash
  sudo make flash-pi FLASH_DEVICE=/dev/sdX
  ```
  or use the new [`just`](https://github.com/casey/just) recipes when you prefer a
  minimal runner without GNU Make:
  ```bash
  sudo FLASH_DEVICE=/dev/sdX just flash-pi
  ```
  Both invocations call `install_sugarkube_image.sh` to keep the local cache fresh before
  writing the media with `flash_pi_media.sh`. The `just` recipe reads `FLASH_DEVICE` (and optional
  `DOWNLOAD_ARGS`) from the environment, so prefix variables as shown when chaining commands.
  Set `DOWNLOAD_ARGS="--release vX.Y.Z"` (or any other flags) in the environment to forward
  custom options into the installer when using `just`.
- Raspberry Pi Imager remains a friendly alternative.
  Use advanced options (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>) to set the
  hostname, credentials and network when flashing `sugarkube.img.xz` manually.
  The repository now ships presets under `docs/templates/pi-imager/` plus a
  renderer script:
  ```bash
  python3 scripts/render_pi_imager_preset.py \
    --preset docs/templates/pi-imager/sugarkube-controller.preset.json \
    --secrets ~/sugarkube/secrets.env \
    --apply
  ```
  The command writes your secrets into Raspberry Pi Imager's configuration so
  the advanced options open pre-populated for the next flash.

## 3. Boot and verify
- Insert the card and power on the Pi.
- k3s installs automatically on first boot. Confirm the node is ready:
  ```bash
  sudo kubectl get nodes
  ```
- token.place and dspace run under `projects-compose.service`. Check status:
  ```bash
  sudo systemctl status projects-compose.service
  ```
- systemd now ships a `k3s-ready.target` that depends on the compose service and waits for
  `kubectl get nodes` to report `Ready`. Inspect the target to confirm the cluster finished
  bootstrapping:
  ```bash
  sudo systemctl status k3s-ready.target
  ```
- If the service fails, inspect logs to troubleshoot:
  ```bash
  sudo journalctl -u projects-compose.service --no-pager
  ```
- When symptoms fall outside the happy path, use the
  [Pi Boot & Cluster Troubleshooting Matrix](./pi_boot_troubleshooting.md) to map
  LED patterns, log locations, and fixes.
- Every verifier run now appends a Markdown summary to `/boot/first-boot-report.txt`.
  The report captures hardware details, `cloud-init` status, the results from
  `pi_node_verifier.sh`, and any provisioning or migration steps recorded by
  `/opt/projects/start-projects.sh`. Inspect the file locally after ejecting the
  boot media or on the Pi itself:
  ```bash
  sudo cat /boot/first-boot-report.txt
  ```
- The verifier also checks for a `Ready` k3s node, confirms `projects-compose.service`
  is `active`, and curls the token.place and dspace endpoints. Override the HTTP
  probes by exporting `TOKEN_PLACE_HEALTH_URL`, `DSPACE_HEALTH_URL`, and related
  `*_INSECURE` flags before invoking `/opt/sugarkube/pi_node_verifier.sh`.
- The boot partition now includes recovery hand-offs generated once k3s
  finishes installing:
  - `/boot/sugarkube-kubeconfig` is a sanitized kubeconfig whose secrets are
    redacted. Share it with operators who only need cluster endpoints and
    certificate authorities.
  - `/boot/sugarkube-kubeconfig-full` is the raw admin kubeconfig from the Pi.
    Store it securely after ejecting the media or copy it into your own
    workstation to bootstrap kubectl access immediately.
  - `/boot/sugarkube-node-token` contains the k3s cluster join token. Use it to
    recover stalled boots, enroll new agents, or reseed the control plane.
  Copy any of these files from another machine after ejecting the boot media.
  Regenerate fresh copies later with `sudo k3s kubectl config view --raw` or
  `sudo cat /var/lib/rancher/k3s/server/node-token` if you need to rotate them.

The image is now ready for additional repositories or joining a multi-node
k3s cluster.

### Clone the SD card to SSD with confidence

Run the new clone helper to replicate the active SD card onto an attached SSD.
Always start with a dry-run so you can review the planned steps before any
blocks are written:

```bash
sudo ./scripts/ssd_clone.py --target /dev/sda --dry-run
```

Drop `--dry-run` once you are ready for the clone. The helper replicates the
partition table, formats the target partitions, rsyncs `/boot` and `/`, updates
`cmdline.txt`/`fstab` with the fresh PARTUUIDs, and records progress under
`/var/log/sugarkube/ssd-clone.state.json`. If the process is interrupted, rerun
with `--resume` to continue from the last completed step without repeating
earlier work:

```bash
sudo ./scripts/ssd_clone.py --target /dev/sda --resume
```

Prefer wrappers? Run the equivalent Makefile or justfile recipes, passing the
target device via `CLONE_TARGET` and additional flags through `CLONE_ARGS`:

```bash
sudo CLONE_TARGET=/dev/sda make clone-ssd CLONE_ARGS="--dry-run"
sudo CLONE_TARGET=/dev/sda just clone-ssd CLONE_ARGS="--resume"
```

Check `/var/log/sugarkube/ssd-clone.state.json` for step-level progress and
`/var/log/sugarkube/ssd-clone.done` once the run completes. Continue with
validation before rebooting into the SSD.

### Validate SSD clones

After migrating the root filesystem to an SSD, run the new validation helper to confirm every layer
references the fresh drive and to sanity-check storage throughput:

```bash
sudo ./scripts/ssd_post_clone_validate.py
```

The script compares `/etc/fstab`, `/boot/cmdline.txt`, and the EEPROM boot order against the live
mounts, then performs a configurable read/write stress test. Reports are stored under
`~/sugarkube/reports/ssd-validation/<timestamp>/`. Prefer the wrappers? Run
`sudo make validate-ssd-clone` or `sudo just validate-ssd-clone` to call the same helper and respect
`VALIDATE_ARGS`. See [`SSD Post-Clone Validation`](./ssd_post_clone_validation.md) for flag details
and sample outputs.

### Monitor SSD health (optional)

Run the SMART monitor whenever you want to record wear levels or temperatures:

```bash
sudo ./scripts/ssd_health_monitor.py --tag post-clone
```

The helper auto-detects the active root device (or accepts `--device /dev/sdX` overrides), captures
`smartctl` output, and stores Markdown/JSON reports under
`~/sugarkube/reports/ssd-health/<timestamp>/`. Prefer wrappers? Use
`sudo make monitor-ssd-health HEALTH_ARGS="--tag weekly"` or the matching `just monitor-ssd-health`
recipe. See the [SSD Health Monitor](./ssd_health_monitor.md) guide for threshold tuning and the
systemd timer example when you want recurring snapshots.

### Recover from SSD issues

If an SSD migration fails or you need to boot from the original SD card again,
run the rollback helper to restore `/boot/cmdline.txt` and `/etc/fstab` to the
SD defaults:

```bash
sudo ./scripts/rollback_to_sd.sh --dry-run
```

Review the planned changes, drop `--dry-run` when ready, then reboot. The script
stores backups and writes a Markdown report to `/boot/sugarkube-rollback-report.md`.
See [SSD Recovery and Rollback](./ssd_recovery.md) for the full walkthrough and
Makefile/justfile shortcuts.

## Codespaces-friendly automation

- Launch a new GitHub Codespace on this repository using the default Ubuntu image.
- Run `just codespaces-bootstrap` once to install `gh`, `pv`, and other helpers that the
  download + flash scripts expect.
- Use `just install-pi-image` or `just download-pi-image` to populate `~/sugarkube/images` with
  the latest release, or trigger `sudo FLASH_DEVICE=/dev/sdX just flash-pi` when you attach a USB
  flasher to the Codespace via the browser or VS Code desktop.
- `just doctor` remains available to validate tooling from within the Codespace without juggling
  Makefiles or bespoke shell aliases.
