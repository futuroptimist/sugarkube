# Minimal Raspberry Pi Image for k3s

This guide shows how to build a lightweight Raspberry Pi OS image for a Raspberry
Pi 5 k3s cluster. The image includes Docker and basic utilities so each node is
ready to join the cluster after flashing.

The build script [`scripts/build_pi_image.sh`](../scripts/build_pi_image.sh)
wraps Raspberry Pi's [`pi-gen`](https://github.com/RPi-Distro/pi-gen) project. It
clones the `arm64` branch, runs only stages 0–2, and disables recommended
packages to keep builds fast. Environment variables let you customize mirrors,
timeouts, and output paths:

- `PI_GEN_URL` – alternate pi-gen repository
- `PI_GEN_BRANCH` – branch to clone (`arm64` by default)
- `IMG_NAME` and `OUTPUT_DIR` – control image filename and location
- `DEBIAN_MIRROR` and `RPI_MIRROR` – override apt mirrors
- `BUILD_TIMEOUT` – maximum build time (default: `4h`)
- `CLOUD_INIT_PATH` – cloud-init configuration to embed

The default cloud-init file installs Docker, the compose plugin, `curl`, and
`git`, then enables the Docker service. Ensure `curl`, `docker` (with its daemon
running), `git`, `sha256sum`, `stdbuf`, `timeout`, and `xz` are installed on the
build host.

## Steps

1. Download the latest prebuilt Sugarkube image from the
   [pi-image workflow artifacts](https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml)
   and verify it:
   ```sh
   sha256sum -c sugarkube.img.xz.sha256
   ```
2. Flash the image with Raspberry Pi Imager using **Use custom**.
3. Boot the Pi and optionally clone the OS to an SSD with `sudo rpi-clone sda -f`.
4. SSH to the Pi and verify Docker:
   ```sh
   sudo systemctl status docker --no-pager
   docker compose version
   ```
5. Install k3s on the nodes following
   [raspi_cluster_setup.md](raspi_cluster_setup.md) and
   [network_setup.md](network_setup.md).

## GitHub Actions

The `pi-image` workflow runs `scripts/build_pi_image.sh`, compresses the result
to `sugarkube.img.xz`, and uploads it as an artifact. Logs stream line-by-line
so progress remains visible during the long-running build.
