# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

## 1. Build or download the image

1. Fetch the latest release with checksum verification:
   ```bash
   ./scripts/sugarkube-latest
   ```
   The script resolves the newest GitHub release, resumes partially-downloaded
   artifacts, verifies the SHA-256 checksum, and stores the image at
   `~/sugarkube/images/sugarkube.img.xz`. Override the destination with
   `--output /path/to/custom.img.xz` when needed.
   Release notes link to `sugarkube.img.xz.manifest.json`, which records the
   pi-gen commit, stage timings, and cosign signatures for every artifact.
2. In GitHub, open **Actions → pi-image → Run workflow** for a fresh build.
   - Tick **token.place** and **dspace** to bake those repos into `/opt/projects`.
   - Wait for the run to finish; it uploads `sugarkube.img.xz` as an artifact.
   - If you prefer to download artifacts manually, use
     `./scripts/download_pi_image.sh --output /your/path.img.xz` to verify and
     resume downloads automatically.
3. Alternatively, build on your machine:
   ```bash
   ./scripts/build_pi_image.sh
   ```
   Skip either project with `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`.
4. After any download or build, verify integrity:
   ```bash
   sha256sum -c path/to/sugarkube.img.xz.sha256
   ```
   The command prints `OK` when the checksum matches the downloaded image.

## 2. Flash with Raspberry Pi Imager
- Write `sugarkube.img.xz` to a microSD card with Raspberry Pi Imager.
- Use advanced options (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>) to set the
  hostname, credentials and network.

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

The image is now ready for additional repositories or joining a multi-node
k3s cluster.
