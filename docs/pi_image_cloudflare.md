# Raspberry Pi Image with Cloudflare Tunnel

This guide expands the
[token.place](https://github.com/futuroptimist/token.place) Raspberry Pi
deployment into a reusable image capable of hosting multiple projects, including
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace).

It uses `cloud-init` to update and upgrade packages, bake Docker, the compose
plugin, the Cloudflare apt repository, and a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
into the OS image. The `build_pi_image.sh` script clones `pi-gen` using
`PI_GEN_BRANCH` (default: `bookworm` for 32-bit builds and `arm64` for
64-bit). Set `PI_GEN_URL` to use a fork or mirror if the default repository is
unavailable. `IMG_NAME` controls the output filename and `OUTPUT_DIR` selects
where artifacts are written; the script creates the directory if needed. To
reduce flaky downloads it pins the official Raspberry Pi and Debian mirrors and
passes `APT_OPTS` so apt retries on transient timeouts. Override the Raspberry Pi
packages mirror with `RPI_MIRROR` (mapped to pi-gen's `APT_MIRROR_RASPBERRYPI`) and
the Debian mirror with `DEBIAN_MIRROR`. Use `BUILD_TIMEOUT` (default: `4h`) to
adjust the maximum build duration and `CLOUD_INIT_PATH` to load a custom
cloud-init configuration instead of the default `scripts/cloud-init/user-data.yaml`.
Set `TUNNEL_TOKEN` to bake a Cloudflare token into
`/opt/sugarkube/.cloudflared.env`; otherwise edit the file after boot.
Ensure `curl`, `docker` (with its daemon running), `git`, `sha256sum`, `stdbuf`,
`timeout`, and `xz` are installed before running it; `stdbuf` and `timeout`
come from GNU coreutils. The script checks that both the temporary and output
directories have at least 10 GB free before starting. Use the prepared image to
deploy
containerized apps. The companion guide
[docker_repo_walkthrough.md](docker_repo_walkthrough.md) explains how to run
projects such as token.place and dspace. Use the resulting image to bootstrap a
three-node k3s cluster; see [raspi_cluster_setup.md](raspi_cluster_setup.md)
for onboarding steps.

## Steps

1. Download the latest prebuilt Sugarkube Raspberry Pi OS image from the
   [pi-image workflow artifacts](https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml)
   and verify it: `sha256sum -c sugarkube.img.xz.sha256`.
2. Flash the image with Raspberry Pi Imager. Open the tool, choose **Use custom**,
   browse for the downloaded file, and write it to your SD card.
3. Boot the Pi and run `sudo rpi-clone sda -f` to copy the OS to an SSD.
4. The build script copies `docker-compose.cloudflared.yml` into
   `/opt/sugarkube/`. Cloud-init adds the Cloudflare apt repo, pre-creates
   `/opt/sugarkube/.cloudflared.env` with `0600` permissions, and enables the
   Docker service; verify both files and the service.
5. Add your Cloudflare token to `/opt/sugarkube/.cloudflared.env` if it wasn't
   provided via `TUNNEL_TOKEN` during the build.
6. Start the tunnel with `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d`.
7. Confirm the tunnel is running: `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml ps` should show `cloudflared` as `Up`.
8. View the tunnel logs to confirm a connection:
   `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml logs -f`.
9. Clone target projects:
   - `git clone https://github.com/futuroptimist/token.place.git`
   - `git clone https://github.com/democratizedspace/dspace.git`
10. Add more `docker-compose` files for additional services.

## GitHub Actions

The `pi-image` workflow builds the OS image with `scripts/build_pi_image.sh`,
ensures the result is available as `sugarkube.img.xz` (compressing the image if
pi-gen produces an uncompressed `.img`), searches recursively in pi-gen's
`deploy/` directory for the image, and exits with an error if none is found.
It then uploads the artifact. Download it
from the [workflow artifacts](https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml)
or run the script locally if you need customizations. The workflow rotates its
cached pi-gen Docker image monthly by hashing the upstream branch, ensuring each
build pulls in the latest security updates.
The build script streams output line-by-line so GitHub Actions logs show
progress during the long-running image creation process.
