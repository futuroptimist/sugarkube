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
builds. Set `IMG_NAME` to change the image name or `OUTPUT_DIR` to control
where artifacts are written. Ensure `docker` (with its daemon running), `xz`,
`git`, and `sha256sum` are installed before running it. Use the prepared image
to deploy containerized apps. The companion guide
[docker_repo_walkthrough.md](docker_repo_walkthrough.md) explains how to run
projects such as token.place and dspace. Use the resulting image to bootstrap a
three-node k3s cluster; see [raspi_cluster_setup.md](raspi_cluster_setup.md)
for onboarding steps.

## Checklist

- [ ] Build or download a Raspberry Pi OS image. `scripts/build_pi_image.sh`
      embeds `scripts/cloud-init/user-data.yaml`, verifies `docker` (and its
      daemon is running), `xz`, `git`, and `sha256sum` are installed, honors
      `IMG_NAME` and `OUTPUT_DIR`, and only uses `sudo` when required.
      `scripts/download_pi_image.sh` fetches the latest prebuilt image via the
      GitHub CLI, or you can grab it from the Actions tab with
      `gh run download -n pi-image`.
- [ ] Verify the download: `sha256sum -c sugarkube.img.xz.sha256`.
- [ ] If downloaded, decompress it with `xz -d sugarkube.img.xz`.
- [ ] (Optional) If building the image manually, place `scripts/cloud-init/user-data.yaml`
      on the SD card's boot partition as `user-data`.
- [ ] Flash the image with Raspberry Pi Imager.
- [ ] Boot the Pi and run `sudo rpi-clone sda -f` to copy the OS to an SSD.
- [ ] Cloud-init adds the Cloudflare apt repo, writes
      `/opt/sugarkube/docker-compose.cloudflared.yml`, pre-creates
      `/opt/sugarkube/.cloudflared.env` with `0600` permissions, and enables the
      Docker service; verify all three.
- [ ] Add your Cloudflare token to `/opt/sugarkube/.cloudflared.env`.
- [ ] Start the tunnel with `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d`.
- [ ] Confirm the tunnel is running: `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml ps` should show `cloudflared` as `Up`.
- [ ] View the tunnel logs to confirm a connection:
      `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml logs -f`.
- [ ] Clone target projects:
  - [ ] `git clone https://github.com/futuroptimist/token.place.git`
  - [ ] `git clone https://github.com/democratizedspace/dspace.git`
- [ ] Add more `docker-compose` files for additional services.

## GitHub Actions

The `pi-image` workflow builds the OS image with `scripts/build_pi_image.sh`,
compresses it to `sugarkube.img.xz`, and uploads it as an artifact. Download it
from the Actions tab or run the script locally if you need customizations.
