# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

## 1. Build or download the image

1. Fetch, verify, and expand the latest release with one command:
   ```bash
   ./scripts/install_sugarkube.sh
   ```
   The installer ensures the GitHub CLI is available, resolves the newest
   release, verifies the checksum with either `sha256sum` or `shasum`, expands
   the image to `~/sugarkube/images/sugarkube.img`, and preserves the compressed
   artifact when `--keep-xz` is supplied.

   Prefer make-style workflows? The repository now exposes
   `make download-pi-image`, `make install-pi-image`, and
   `make flash-pi DEVICE=/dev/sdX` helpers. Pass extra flags via the
   `DOWNLOAD_FLAGS`, `INSTALL_FLAGS`, or `FLASH_ARGS` variables, e.g.
   `make install-pi-image INSTALL_FLAGS="--keep-xz"`.
2. To produce a fresh build instead of consuming a release, trigger
   **Actions → pi-image → Run workflow**. Artifacts still land at
   `~/sugarkube/images/` when downloaded through `install_sugarkube.sh` or
   `download_pi_image.sh`.
3. Building locally remains unchanged:
   ```bash
   ./scripts/build_pi_image.sh
   ```
   Skip either project with `CLONE_TOKEN_PLACE=false` or `CLONE_DSPACE=false`.
4. After any download or build, verify integrity when working manually:
   ```bash
   sha256sum -c path/to/sugarkube.img.xz.sha256
   ```
   The command prints `OK` when the checksum matches the downloaded image.

## 2. Flash media

Choose the flow that fits your workstation:

- **Automated CLI flashing** – `scripts/flash_pi_media.sh` discovers removable
  disks, streams `.img.xz` files with `xzcat | dd`, computes SHA-256 digests
  while writing, and re-reads the device to confirm the checksum. Invoke it
  directly or through `make flash-pi DEVICE=/dev/sdX FLASH_ARGS="--yes"` to skip
  interactive confirmation.
- **macOS/Windows** – `scripts/flash_pi_media.ps1` mirrors the Linux helper
  using PowerShell and supports piping decompressed bytes into
  `\\.\PhysicalDriveN` with byte-for-byte verification.
- **Raspberry Pi Imager** – import the presets under `docs/presets/` to pre-fill
  hostname, Wi-Fi, SSH keys, and the official sugarkube download URL. Advanced
  options (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>X</kbd>) remain available for
  last-minute overrides.

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

## 4. Headless provisioning

Use `docs/pi_image_headless.md` to inject Wi-Fi credentials, Cloudflare tokens,
and SSH keys without modifying repository files. The guide covers using
`scripts/cloud-init/user-data.yaml`, populating `secrets.env`, and applying the
same configuration inside Codespaces so a fresh image boots directly into a
working `projects-compose` stack.
