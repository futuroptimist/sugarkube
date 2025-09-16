# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

## 1. Build or download the image

1. Fetch the latest release with checksum verification. Use whichever path fits
   your workflow:
   - **One-liner installer** – downloads, verifies, and expands the image:
     ```bash
     curl -fsSL https://raw.githubusercontent.com/futuroptimist/sugarkube/main/scripts/install_sugarkube.sh | bash
     ```
     Add `--dry-run` to inspect the steps or pass `--output` to change the raw
     image location. The installer installs `gh` if it is missing, resumes
     partial downloads, and leaves `sugarkube.img` and `.img.xz` in
     `~/sugarkube/images/` by default.
   - **Repository script** – only downloads + verifies the release artifact:
     ```bash
     ./scripts/sugarkube-latest
     ```
     Use this when working inside the repository or when you want to keep the
     compressed `.img.xz` file for flashing utilities that understand it
     directly.
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
- Review `/boot/first-boot-report/` or `/boot/first-boot-report.txt` for a
  JSON/HTML/text status bundle created by `sugarkube-first-boot.service`. The
  report lists filesystem expansion, networking status, verifier output, and
  the exported kubeconfig + node token paths.

The image is now ready for additional repositories or joining a multi-node
k3s cluster.
