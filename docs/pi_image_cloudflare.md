# Raspberry Pi Image with Cloudflare Tunnel

This guide generalizes the [token.place](https://github.com/futuroptimist/token.place)
Raspberry Pi deployment so it can host multiple projects such as
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace).

It bakes Docker, the compose plugin, and a Cloudflare Tunnel into the OS image
using `cloud-init`. The `build_pi_image.sh` script clones `pi-gen` using the
`PI_GEN_BRANCH` environment variable, defaulting to `bookworm` for reproducible
builds. Ensure `docker`, `git`, and `xz` are installed before running the
script. Use the prepared image to deploy containerized apps. The companion guide
[docker_repo_walkthrough.md](docker_repo_walkthrough.md) explains how to run
projects such as token.place and dspace.

## Checklist

- [ ] Build or download a Raspberry Pi OS image. `scripts/build_pi_image.sh` now embeds
      `scripts/cloud-init/user-data.yaml`, checks for `docker`, `git`, and `xz`, and only uses `sudo` when required.
- [ ] If downloaded, decompress it with `xz -d sugarkube.img.xz`.
- [ ] (Optional) If building the image manually, place `scripts/cloud-init/user-data.yaml`
      on the SD card's boot partition as `user-data`.
- [ ] Flash the image with Raspberry Pi Imager.
- [ ] Boot the Pi and run `sudo rpi-clone sda -f` to copy the OS to an SSD.
- [ ] Cloud-init writes `/opt/sugarkube/docker-compose.cloudflared.yml`; verify it exists.
- [ ] Add your Cloudflare token to `/opt/sugarkube/.cloudflared.env`.
- [ ] Start the tunnel with `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d`.
- [ ] Confirm the tunnel is running: `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml ps` should show `cloudflared` as `Up`.
- [ ] Clone target projects:
  - [ ] `git clone https://github.com/futuroptimist/token.place.git`
  - [ ] `git clone https://github.com/democratizedspace/dspace.git`
- [ ] Add more `docker-compose` files for additional services.

## GitHub Actions

The `pi-image` workflow builds the OS image with `scripts/build_pi_image.sh`,
compresses it to `sugarkube.img.xz`, and uploads it as an artifact. Download it
from the Actions tab or run the script locally if you need customizations.
