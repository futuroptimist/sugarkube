# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

## 1. Build or download the image

1. In GitHub, open **Actions → pi-image → Run workflow**.
   - Tick **token.place** and **dspace** to bake those repos into `/opt/projects`.
   - Wait for the run to finish; it uploads `sugarkube.img.xz` as an artifact.
2. Download, verify, and expand the artifact automatically:
   ```bash
   ./scripts/sugarkube_latest.sh
   ```
   The script resolves the latest GitHub Release, resumes partial downloads, verifies the
   SHA-256 checksum, and stores `sugarkube.img.xz` plus the expanded `sugarkube.img` under
   `~/sugarkube/images/`. Pass `--no-expand` to keep only the compressed archive or
   `-d <dir>` to override the destination.
3. Alternatively, build on your machine:
   ```bash
   ./scripts/build_pi_image.sh
   ```
   Skip either project with `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`.
4. The download script already writes `sugarkube.img.xz.sha256`. Re-run
   `sha256sum -c sugarkube.img.xz.sha256` if you need to confirm integrity later.

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
