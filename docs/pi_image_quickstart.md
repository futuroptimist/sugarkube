# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

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
- If the service fails, inspect logs to troubleshoot:
  ```bash
  sudo journalctl -u projects-compose.service --no-pager
  ```
- Every verifier run now appends a Markdown summary to `/boot/first-boot-report.txt`.
  The report captures hardware details, `cloud-init` status, the results from
  `pi_node_verifier.sh`, and any provisioning or migration steps recorded by
  `/opt/projects/start-projects.sh`. Inspect the file locally after ejecting the
  boot media or on the Pi itself:
  ```bash
  sudo cat /boot/first-boot-report.txt
  ```

The image is now ready for additional repositories or joining a multi-node
k3s cluster.

## Codespaces-friendly automation

- Launch a new GitHub Codespace on this repository using the default Ubuntu image.
- Run `just codespaces-bootstrap` once to install `gh`, `pv`, and other helpers that the
  download + flash scripts expect.
- Use `just install-pi-image` or `just download-pi-image` to populate `~/sugarkube/images` with
  the latest release, or trigger `sudo FLASH_DEVICE=/dev/sdX just flash-pi` when you attach a USB
  flasher to the Codespace via the browser or VS Code desktop.
- `just doctor` remains available to validate tooling from within the Codespace without juggling
  Makefiles or bespoke shell aliases.
