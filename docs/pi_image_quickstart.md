# Pi Image Quickstart

Build a Raspberry Pi OS image that boots with k3s and the
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace) services.

## 1. Build or download the image
- From the GitHub Actions tab, run the `pi-image` workflow. Check the boxes to
  clone `token.place` and `dspace` so they deploy automatically on first boot.
- After the workflow completes, fetch the `sugarkube.img.xz` artifact via
  `./scripts/download_pi_image.sh` (uses the GitHub CLI), or build locally with
  `./scripts/build_pi_image.sh`.

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

The image is now ready for additional repositories or joining a multi-node
k3s cluster.
