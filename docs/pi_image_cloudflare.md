# Raspberry Pi Image with Cloudflare Tunnel

This guide expands the
[token.place](https://github.com/futuroptimist/token.place) Raspberry Pi
deployment into a reusable image capable of hosting multiple projects, including
[token.place](https://github.com/futuroptimist/token.place) and
[dspace](https://github.com/democratizedspace/dspace).

It uses `cloud-init` to update and upgrade packages, bake Docker, the compose
plugin, the Cloudflare apt repository, and a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
into the OS image. Cloud-init also drops an apt config with five retries and
30-second timeouts to smooth over flaky networks.
The `build_pi_image.sh` script clones `pi-gen` using
`PI_GEN_BRANCH` (default: `bookworm` for 32-bit builds and `arm64` for
64-bit). Set `PI_GEN_URL` to use a fork or mirror if the default repository is
unavailable. `IMG_NAME` controls the output filename and `OUTPUT_DIR` selects
where artifacts are written; the script creates the directory if needed. To avoid
accidental overwrites it aborts when the image already exists unless
`FORCE_OVERWRITE=1` is set. Set `FORCE_OVERWRITE=1` when rerunning builds to
replace an existing image. To reduce flaky downloads it pins the official
Raspberry Pi and Debian mirrors, adds `APT_OPTS` (retries, timeouts,
`--fix-missing`), and installs a persistent apt/dpkg Pre-Invoke hook that rewrites
any raspbian host to a stable HTTPS mirror and bypasses proxies for
`archive.raspberrypi.com`. Set `SKIP_MIRROR_REWRITE=1` to disable these rewrites
when your network already uses a reliable mirror. Use `APT_RETRIES` and
`APT_TIMEOUT` to tune the retry count and per-request timeout. Override the
Raspberry Pi packages mirror with `RPI_MIRROR` (mapped to pi-gen's
`APT_MIRROR_RASPBERRYPI`) and the Debian mirror with `DEBIAN_MIRROR`. Use
`BUILD_TIMEOUT` (default: `4h`) to adjust the maximum build duration. Customize
the cloud-init configuration with `CLOUD_INIT_PATH` or point `CLOUD_INIT_DIR` and
`CLOUDFLARED_COMPOSE_PATH` at alternate files; the defaults read from
`scripts/cloud-init/`. Set `SKIP_BINFMT=1` to skip installing binfmt handlers when
they're already present or when the build environment disallows privileged
containers.
