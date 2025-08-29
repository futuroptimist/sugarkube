# Pi Image Builder – Design

## Goals
- Deterministic, reproducible Raspberry Pi OS images with cloud-init customizations
- Cross-platform developer experience (Windows, macOS, Linux)
- Resilient to transient mirror/network failures; recoverable without manual surgery
- CI-friendly: same config can run locally and in GitHub Actions

## Inputs / Outputs
- Inputs:
- `scripts/cloud-init/user-data.yaml` (cloud-init seed)
- `scripts/cloud-init/docker-compose.cloudflared.yml` (Cloudflare Tunnel compose file)
  - Environment variables: `PI_GEN_BRANCH` (default `bookworm`), `IMG_NAME` (default `sugarkube`), `ARM64` (default `1`), optional `OUTPUT_DIR`, `PI_GEN_STAGES` (default `stage0 stage1 stage2`)
- Outputs:
  - `IMG_NAME.img.xz` and `IMG_NAME.img.xz.sha256` in `OUTPUT_DIR`. pi-gen
    exports a `*.img.zip` which this script unzips before recompressing to
    `xz`.

## Build Strategies

1) Native shell (preferred when available)
- Linux/WSL/Git Bash executes upstream `pi-gen/build.sh` directly
- Pros: fewer layers, fastest when native Linux
- Cons: requires bash and Docker daemon available

2) Official container path (primary Windows fallback)
- Image: `ghcr.io/raspberrypi/pigen`
- Bind mounts:
  - `/pi-gen/deploy` → host `OUTPUT_DIR`
  - `/pi-gen/work` → persistent Docker volume `pigen-work-cache`
  - `/var/cache/apt` → persistent Docker volume `pigen-apt-cache`
  - `stage2/01-sys-tweaks/user-data` → host `scripts/cloud-init/user-data.yaml`
  - `stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml` → host compose file
- Env:
  - `IMG_NAME`, `ENABLE_SSH=1`, `ARM64`, `USE_QCOW2=1`
  - Mirrors: `APT_MIRROR`, `RASPBIAN_MIRROR`, `APT_MIRROR_RASPBIAN`, `APT_MIRROR_RASPBERRYPI`, `DEBIAN_MIRROR`
  - `APT_OPTS` with retries, timeouts, `--fix-missing`
- Pros: Maintained upstream runtime, persistent caches improve reliability
- Cons: Requires `tonistiigi/binfmt` installed on host to emulate ARM

3) Debian container path (secondary fallback)
- Starts from `debian:bookworm`, installs `pi-gen` dependencies including `qemu-user-static`
- Configures mirrors and `USE_QCOW2=1`, mounts `binfmt_misc` if needed
- Pros: Works when `ghcr.io/raspberrypi/pigen` is unavailable
- Cons: Larger bootstrap; slower first-run

## Reliability Features
- Mirror hardening: default to `deb.debian.org` and official Raspberry Pi mirrors
- `APT_OPTS` with retries, timeouts, `--fix-missing`, and disabled recommends
- `USE_QCOW2=1` for faster, space-efficient stages and resilient restarts
- Persistent `work` and APT cache volumes in official path
- Host `binfmt` installation via `tonistiigi/binfmt` (arm, arm64)
- Clear fast-fail on missing Docker daemon

## Windows-specific Notes
- PowerShell script `scripts/build_pi_image.ps1`:
  - Detects WSL (`wsl.exe`) and Git Bash (`bash.exe`); prefers Git Bash for
    Docker Desktop, falls back to WSL
  - Converts Windows paths to MSYS (`/c/...`) and WSL (`/mnt/c/...`) accurately
  - If local shell fails, tries official `pigen` container, then Debian fallback
  - Compresses with native `xz`, `7z`, WSL `xz`, or Docker `xz` as needed

## CI Considerations
- CI can run the official container path with the same env mirrors and qcow2
  - Artifacts: upload `IMG_NAME.img.xz` and checksum; retain `deploy/` (with the
    original `*.img.zip`) in run artifacts if needed
- Default `PI_GEN_STAGES` only builds `stage0`–`stage2` so CI skips heavyweight desktop
  packages. Override to build a full image.

## Operations & Recovery
- If apt stalls: rerun; caches and retries reduce recurrence
- If mirrors fail: consider toggling Raspbian mirror env to a known-good mirror
- If `binfmt_misc` errors: rerun host `tonistiigi/binfmt` installer
- Disk requirements: ≥30 GB free; Docker Desktop resources: ≥4 CPUs, ≥8–12 GB RAM

## Security
- Read-only mounts for cloud-init and compose files into container
- No secrets embedded; Cloudflare token remains empty by default

## Future Enhancements
- Parametrize mirror list and implement automatic mirror failover
- Structured logs from `pi-gen` stages to summarize progress/time
- Add GitHub workflow to publish images nightly with cache re-use
