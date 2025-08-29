# Raspberry Pi Image with Cloudflare Tunnel

This guide expands the
[token.place](https://github.com/futuroptimist/token.place) Raspberry Pi
deployment into a reusable image capable of hosting multiple projects, including
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace).

It uses `cloud-init` to bake Docker, the compose plugin, the Cloudflare apt
repository, and a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
into the OS image. The `build_pi_image.sh` script clones `pi-gen` using the
`PI_GEN_BRANCH` environment variable, defaulting to `bookworm` for reproducible
builds. Set `PI_GEN_URL` to use a fork or mirror if the default repository is
unavailable. Set `IMG_NAME` to change the image name or `OUTPUT_DIR` to control
where artifacts are written; the script creates the directory if needed. Use
`CLOUD_INIT_PATH` (or override `CLOUD_INIT_DIR`) to load a custom cloud-init
configuration instead of the default `scripts/cloud-init/user-data.yaml`.
Ensure `docker` (with its daemon running), `xz`, `git`, and `sha256sum` are
installed before running it. Use the prepared image to deploy containerized
apps. The companion guide
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
5. Add your Cloudflare token to `/opt/sugarkube/.cloudflared.env`.
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
compresses it to `sugarkube.img.xz`, and uploads it as an artifact. Download it
from the [workflow artifacts](https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml)
or run the script locally if you need customizations. The workflow rotates its
cached pi-gen Docker image monthly by hashing the upstream branch, ensuring each
build pulls in the latest security updates.
The build script streams output line-by-line so GitHub Actions logs show
progress during the long-running image creation process.
