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
reduce flaky downloads it pins the official Raspberry Pi and Debian mirrors,
adds `APT_OPTS` (retries, timeouts, `--fix-missing`), and installs a persistent
apt/dpkg Pre-Invoke hook that rewrites any raspbian host to a stable HTTPS
mirror, and bypasses proxies for `archive.raspberrypi.com`. Override the Raspberry
Use `APT_RETRIES` and `APT_TIMEOUT` to tune the retry count and per-request timeout.
Pi packages mirror with `RPI_MIRROR` (mapped to pi-gen's `APT_MIRROR_RASPBERRYPI`)
and the Debian mirror with `DEBIAN_MIRROR`. Use `BUILD_TIMEOUT` (default: `4h`)
to adjust the maximum build duration. Customize the cloud-init configuration with
`CLOUD_INIT_PATH` or point `CLOUD_INIT_DIR` and `CLOUDFLARED_COMPOSE_PATH` at
alternate files; the defaults read from `scripts/cloud-init/`. Set `SKIP_BINFMT=1`
to skip installing binfmt handlers when they're already present or when the build
environment disallows privileged containers.

`REQUIRED_SPACE_GB` (default: `10`) controls the free disk space check.
The script rewrites the Cloudflare apt source architecture to `armhf` when
`ARM64=0` so 32-bit builds install the correct packages and sets `ARMHF=0` when
`ARM64=1` to avoid generating both architectures.

The image embeds `pi_node_verifier.sh` in `/usr/local/sbin` and clones the
`token.place` and `democratizedspace/dspace` (branch `v3`) repositories into
`/opt/projects` by default. Set `CLONE_SUGARKUBE=true` to include this repo and
pass space-separated Git URLs in `EXTRA_REPOS` to pull additional projects.

Set `TUNNEL_TOKEN` or `TUNNEL_TOKEN_FILE` to bake a Cloudflare token into
`/opt/sugarkube/.cloudflared.env`; otherwise edit the file after boot. The image
installs a `cloudflared-compose` systemd unit which starts the tunnel via Docker
once the token is present and waits for `network-online.target` to ensure
connectivity. The script curls the Debian, Raspberry Pi, and pi-gen repositories
with a 10-second timeout before building; override this via the
`URL_CHECK_TIMEOUT` environment variable. Ensure `curl`, `docker` (with its
daemon running), `git`, `sha256sum`, `stdbuf`, `timeout`, and `xz` are installed
before running it; `stdbuf` and `timeout` come from GNU coreutils. The script
checks that both the temporary and output directories have at least 10 GB free
before starting. Use the prepared image to deploy containerized apps. The
companion guide [docker_repo_walkthrough.md](docker_repo_walkthrough.md)
explains how to run projects such as token.place and dspace. Use the resulting
image to bootstrap a three-node k3s cluster; see
[raspi_cluster_setup.md](raspi_cluster_setup.md) for onboarding steps.

## Steps

1. Download the latest prebuilt Sugarkube Raspberry Pi OS image from the
   [pi-image workflow artifacts][pi-image workflow artifacts] and verify it:
   `sha256sum -c sugarkube.img.xz.sha256`.
2. Flash the image with Raspberry Pi Imager. Open the tool, choose **Use custom**,
   browse for the downloaded file, and write it to your SD card.
3. Boot the Pi and run `sudo rpi-clone sda -f` to copy the OS to an SSD.
4. The build script copies `docker-compose.cloudflared.yml` (override with
   `CLOUDFLARED_COMPOSE_PATH`) into `/opt/sugarkube/`. Cloud-init adds the
   Cloudflare apt repo, pre-creates
   `/opt/sugarkube/.cloudflared.env` with `0600` permissions, installs the
   `cloudflared-compose` systemd unit (wired to `network-online.target` and set
   to restart on failure), enables Docker, and removes the apt cache and package
   lists to shrink the image. If the default `pi` user exists it's added to the
   `docker` group and given ownership of `/opt/sugarkube`. When the `pi` user is
   absent these steps are skipped without error. For custom usernames, adjust
   `user-data.yaml` accordingly. Verify the files and service.
5. Add your Cloudflare token to `/opt/sugarkube/.cloudflared.env` if it wasn't
   provided via `TUNNEL_TOKEN` or `TUNNEL_TOKEN_FILE` during the build. The
   tunnel starts automatically when the token exists; otherwise run:
   `sudo systemctl enable --now cloudflared-compose`.
6. Confirm the tunnel is running:
   `systemctl status cloudflared-compose --no-pager` should show `active`.
7. View the tunnel logs to confirm a connection:
   `journalctl -u cloudflared-compose -f`.
8. If any repositories were selected during the build, explore them under
   `/opt/projects` (e.g. `sugarkube`, `token.place`, or `dspace` on branch
   `v3`).
9. Add more `docker-compose` files for additional services.

## GitHub Actions

The `pi-image` workflow builds the OS image with `scripts/build_pi_image.sh`,
ensures the result is available as `sugarkube.img.xz` (compressing the image if
pi-gen produces an uncompressed `.img`), searches recursively in pi-gen's
`deploy/` directory for the image, and exits with an error if none is found.
It then uploads the artifact. Download it
   from the [workflow artifacts][pi-image workflow artifacts] or run the script
   locally if you need customizations. The workflow rotates its
cached pi-gen Docker image monthly by hashing the upstream branch, ensuring each
build pulls in the latest security updates.
The build script streams output line-by-line so GitHub Actions logs show
progress during the long-running image creation process.

[pi-image workflow artifacts]:
  https://github.com/futuroptimist/sugarkube/actions/workflows/pi-image.yml
