#!/usr/bin/env bash
set -euo pipefail

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires curl, docker, git, sha256sum, stdbuf, timeout, xz and roughly 10 GB of
# free disk space. Set PI_GEN_URL to override the default pi-gen repository.

for cmd in curl docker git sha256sum stdbuf timeout xz; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd is required" >&2
    exit 1
  fi
done

# Ensure the Docker daemon is running; otherwise builds will fail later
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running or not accessible" >&2
  exit 1
fi

# Install qemu binfmt handlers so pi-gen can emulate ARM binaries without hanging
if ! docker run --privileged --rm tonistiigi/binfmt --install arm64,arm >/dev/null 2>&1; then
  echo "Failed to install binfmt handlers on host" >&2
  exit 1
fi

# Use sudo only when not running as root. Some CI containers omit sudo.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "Run as root or install sudo" >&2
    exit 1
  fi
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLOUD_INIT_PATH="${CLOUD_INIT_PATH:-${REPO_ROOT}/scripts/cloud-init/user-data.yaml}"
if [ ! -f "${CLOUD_INIT_PATH}" ]; then
  echo "Cloud-init file not found: ${CLOUD_INIT_PATH}" >&2
  exit 1
fi
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

PI_GEN_URL="${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}"
DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://deb.debian.org/debian}"
RPI_MIRROR="${RPI_MIRROR:-https://archive.raspberrypi.com/debian}"
for url in "$DEBIAN_MIRROR" "$RPI_MIRROR" "$PI_GEN_URL"; do
  if ! curl -fsI "$url" >/dev/null; then
    echo "Cannot reach $url" >&2
    exit 1
  fi
done

ARM64="${ARM64:-1}"
# Clone the arm64 branch when building 64-bit images to avoid generating
# both architectures and exhausting disk space.
if [ -z "${PI_GEN_BRANCH:-}" ]; then
  if [ "$ARM64" -eq 1 ]; then
    PI_GEN_BRANCH="arm64"
  else
    PI_GEN_BRANCH="bookworm"
  fi
fi
IMG_NAME="${IMG_NAME:-sugarkube}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}}"
mkdir -p "${OUTPUT_DIR}"

git clone --depth 1 --single-branch --branch "${PI_GEN_BRANCH}" \
  "${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}" \
  "${WORK_DIR}/pi-gen"

cp "${CLOUD_INIT_PATH}" \
  "${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/user-data"

install -Dm644 "${REPO_ROOT}/scripts/cloud-init/docker-compose.cloudflared.yml" \
  "${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml"

cd "${WORK_DIR}/pi-gen"
export DEBIAN_FRONTEND=noninteractive

# Allow callers to override the build timeout
BUILD_TIMEOUT="${BUILD_TIMEOUT:-4h}"

APT_OPTS='-o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
-o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true'

cat > config <<CFG
IMG_NAME="${IMG_NAME}"
ENABLE_SSH=1
ARM64=${ARM64}
# Prefer primary mirrors to avoid flaky community mirrors and set apt timeouts
APT_MIRROR=http://raspbian.raspberrypi.org/raspbian
RASPBIAN_MIRROR=http://raspbian.raspberrypi.org/raspbian
APT_MIRROR_RASPBERRYPI=http://archive.raspberrypi.org/debian
DEBIAN_MIRROR=http://deb.debian.org/debian
APT_OPTS="${APT_OPTS}"
CFG

# Ensure binfmt_misc mount exists for pi-gen checks (harmless if already mounted)
if [ ! -d /proc/sys/fs/binfmt_misc ]; then
  mkdir -p /proc/sys/fs/binfmt_misc || true
fi
if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
  ${SUDO} mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc || true
fi

echo "Starting pi-gen build..."
# Stream output line-by-line so GitHub Actions shows progress and doesn't appear to hang
${SUDO} stdbuf -oL -eL timeout "${BUILD_TIMEOUT}" ./build.sh
echo "pi-gen build finished"

mv deploy/*.img "${OUTPUT_DIR}/${IMG_NAME}.img"
xz -T0 "${OUTPUT_DIR}/${IMG_NAME}.img"
sha256sum "${OUTPUT_DIR}/${IMG_NAME}.img.xz" > \
  "${OUTPUT_DIR}/${IMG_NAME}.img.xz.sha256"
ls -lh "${OUTPUT_DIR}/${IMG_NAME}.img.xz" \
  "${OUTPUT_DIR}/${IMG_NAME}.img.xz.sha256"
echo "Image written to ${OUTPUT_DIR}/${IMG_NAME}.img.xz"
