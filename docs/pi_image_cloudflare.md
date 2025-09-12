# Raspberry Pi Image with Cloudflare Tunnel

This guide expands the [token.place](https://github.com/futuroptimist/token.place)
Raspberry Pi deployment into a reusable image capable of hosting multiple projects,
including [dspace](https://github.com/democratizedspace/dspace).

It uses `cloud-init` to update and upgrade packages, bake Docker, the compose
plugin, the Cloudflare apt repository, and a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
into the OS image. Cloud-init also drops an apt config with five retries,
30-second timeouts, and `APT::Get::Fix-Missing` enabled to smooth over flaky networks.
It also configures the systemd journal for persistent storage (capped at roughly 200 MB)
so logs survive reboots. After installation, it removes unused packages with
`apt-get autoremove -y` and cleans the apt cache to keep the image small.

The `build_pi_image.sh` script clones [pi-gen](https://github.com/RPi-Distro/pi-gen) using
`PI_GEN_BRANCH` (default: `bookworm` for 32-bit builds and `arm64` for
64-bit). Set `PI_GEN_URL` to use a fork or mirror if the default repository is
unavailable. `IMG_NAME` controls the output filename and `OUTPUT_DIR` selects
where artifacts are written; the script creates the directory if needed. Run
`scripts/build_pi_image.sh --help` for a summary of configurable environment
variables. To avoid accidental overwrites it aborts when the image already
exists unless `FORCE_OVERWRITE=1` is set. Set `FORCE_OVERWRITE=1` when rerunning
builds to replace an existing image. To reduce flaky downloads it pins the
official Raspberry Pi and Debian mirrors, adds `APT_OPTS` (retries, timeouts,
`-o APT::Get::Fix-Missing=true`), and installs a persistent apt/dpkg Pre-Invoke hook
that rewrites any raspbian host to a stable HTTPS mirror and bypasses proxies for
`archive.raspberrypi.com`. Use `APT_REWRITE_MIRROR` to change the rewrite target
(default: `https://mirror.fcix.net/raspbian/raspbian`). Set `SKIP_MIRROR_REWRITE=1`
to disable these rewrites when your network already uses a reliable mirror. Use
`APT_RETRIES` and `APT_TIMEOUT` to tune the retry count and per-request timeout.
Override the Raspberry Pi packages mirror with `RPI_MIRROR` (mapped to pi-gen's
`APT_MIRROR_RASPBERRYPI`) and the Debian mirror with `DEBIAN_MIRROR`. Use
`BUILD_TIMEOUT` (default: `4h`) to adjust the maximum build duration. Customize
the cloud-init configuration with `CLOUD_INIT_PATH` or point `CLOUD_INIT_DIR` and
`CLOUDFLARED_COMPOSE_PATH` at alternate files; the defaults read from
`scripts/cloud-init/`. Set `SKIP_BINFMT=1` to skip installing binfmt handlers when
they're already present or when the build environment disallows privileged
containers. Set `DEBUG=1` to trace script execution for troubleshooting.
Set `KEEP_WORK_DIR=1` to retain the temporary pi-gen work directory instead of
deleting it, which aids debugging failed builds.

`REQUIRED_SPACE_GB` (default: `10`) controls free disk space checks on the
temporary work directory and the output location.
The script rewrites the Cloudflare apt source architecture to `armhf` when
`ARM64=0` so 32-bit builds install the correct packages and sets `ARMHF=0` when
`ARM64=1` to avoid generating both architectures.

The image embeds `pi_node_verifier.sh` in `/usr/local/sbin` and clones the
`token.place` and `democratizedspace/dspace` (branch `v3`) repositories into
`/opt/projects` by default. Set `CLONE_SUGARKUBE=true` to include this repo and
pass space-separated Git URLs in `EXTRA_REPOS` to pull additional projects.
`start-projects.sh` enables the optional `projects-compose` systemd unit on
first boot and now checks for `systemctl`, skipping quietly when systemd isn't
present.

On first boot `init-env.sh` copies each project's `.env.example` to `.env` and
sets its mode to `0600` so secrets stay private.

Set `TUNNEL_TOKEN` or `TUNNEL_TOKEN_FILE` to bake a Cloudflare token into
`/opt/sugarkube/.cloudflared.env`; tokens containing `/` or `&` are escaped
automatically. Otherwise edit the file after boot.
Cloud-init writes `docker-compose.cloudflared.yml` to `/opt/sugarkube`.
This avoids downloading the file at boot.
The image installs a `cloudflared-compose` systemd unit which starts the tunnel via Docker
once the token is present and waits for `network-online.target` to ensure
connectivity. The script curls the Debian, Raspberry Pi, and pi-gen repositories
with a 10-second timeout before building; override this via the
`URL_CHECK_TIMEOUT` environment variable or set `SKIP_URL_CHECK=1` to bypass
these probes when using local mirrors or working offline. Ensure `curl`, `docker`
(with its daemon running), `git`, `sha256sum`, `stdbuf`, `timeout`, `xz`, `bsdtar`, and `df`
are installed before running it; `stdbuf` and `timeout` come from GNU coreutils. The script
checks that both the temporary and output directories have at least 10 GB free
before starting and verifies the resulting image exists and is non-empty before
reporting success. Use the prepared image to deploy containerized apps. The
companion guide [docker_repo_walkthrough.md](docker_repo_walkthrough.md)
explains how to run projects such as token.place and dspace. Use the resulting
image to bootstrap a three-node k3s cluster; see
[raspi_cluster_setup.md](raspi_cluster_setup.md) for onboarding steps.
