# Raspberry Pi Image with Cloudflare Tunnel

This guide generalizes the [token.place](https://github.com/futuroptimist/token.place)
Raspberry Pi deployment so it can host multiple projects such as
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace).

It bakes Docker, the compose plugin, and a Cloudflare Tunnel into the OS image using `cloud-init`.

## Checklist

- [ ] Build or download a Raspberry Pi OS image.
- [ ] Place `scripts/cloud-init/user-data.yaml` on the SD card's boot partition as `user-data`.
- [ ] Flash the image with Raspberry Pi Imager.
- [ ] Boot the Pi and run `sudo rpi-clone sda -f` to copy the OS to an SSD.
- [ ] Reboot and verify `/opt/sugarkube/docker-compose.cloudflared.yml` exists.
- [ ] Add your Cloudflare token to `/opt/sugarkube/.cloudflared.env`.
- [ ] Start the tunnel with `docker compose -f /opt/sugarkube/docker-compose.cloudflared.yml up -d`.
- [ ] Clone target projects:
  - [ ] `git clone https://github.com/futuroptimist/token.place.git`
  - [ ] `git clone https://github.com/democratizedspace/dspace.git`
- [ ] Add more `docker-compose` files for additional services.

## GitHub Actions

Building a full OS image in CI is heavy. If GitHub Actions proves too slow,
run `scripts/build_pi_image.sh` locally on a Linux machine with Docker.
