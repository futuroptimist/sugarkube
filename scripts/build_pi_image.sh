#!/usr/bin/env bash
set -euo pipefail

REQUIRED_SPACE_GB="${REQUIRED_SPACE_GB:-10}"

check_space() {
  local dir="$1"
  local avail_kb required_kb
  avail_kb=$(df -Pk "$dir" | awk 'NR==2 {print $4}')
  required_kb=$((REQUIRED_SPACE_GB * 1024 * 1024))
  if [ "$avail_kb" -lt "$required_kb" ]; then
    echo "Need at least ${REQUIRED_SPACE_GB}GB free in $dir" >&2
    exit 1
  fi
}

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires curl, docker, git, sha256sum, stdbuf, timeout, xz, unzip and roughly
# 10 GB of free disk space. Set PI_GEN_URL to override the default pi-gen
# repository.

for cmd in curl docker git sha256sum stdbuf timeout xz unzip; do
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
  # Some hosts require installing handlers separately
  if ! docker run --privileged --rm tonistiigi/binfmt --install arm64 >/dev/null 2>&1; then
    echo "Failed to install arm64 binfmt handler on host" >&2
    exit 1
  fi
  if ! docker run --privileged --rm tonistiigi/binfmt --install arm >/dev/null 2>&1; then
    echo "Failed to install arm binfmt handler on host" >&2
    exit 1
  fi
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

# Ensure temporary and output locations have enough space
check_space "$(dirname "${WORK_DIR}")"

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
check_space "${OUTPUT_DIR}"

# Build only the minimal lite image by default to keep CI fast
PI_GEN_STAGES="${PI_GEN_STAGES:-stage0 stage1 stage2}"

git clone --depth 1 --single-branch --branch "${PI_GEN_BRANCH}" \
  "${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}" \
  "${WORK_DIR}/pi-gen"

USER_DATA="${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/user-data"
cp "${CLOUD_INIT_PATH}" "${USER_DATA}"
if [ -n "${TUNNEL_TOKEN:-}" ]; then
  echo "Embedding Cloudflare token into cloud-init"
  sed -i "s|TUNNEL_TOKEN=\"\"|TUNNEL_TOKEN=\"${TUNNEL_TOKEN}\"|" "${USER_DATA}"
fi

install -Dm644 "${REPO_ROOT}/scripts/cloud-init/docker-compose.cloudflared.yml" \
  "${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml"

cd "${WORK_DIR}/pi-gen"
export DEBIAN_FRONTEND=noninteractive

# Allow callers to override the build timeout
BUILD_TIMEOUT="${BUILD_TIMEOUT:-4h}"

APT_OPTS='-o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
-o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true'
APT_OPTS+=' -o APT::Install-Recommends=false -o APT::Install-Suggests=false'

cat > config <<CFG
IMG_NAME="${IMG_NAME}"
ENABLE_SSH=1
ARM64=${ARM64}
# Prefer primary mirrors to avoid flaky community mirrors and set apt timeouts
APT_MIRROR=http://raspbian.raspberrypi.org/raspbian
RASPBIAN_MIRROR=http://raspbian.raspberrypi.org/raspbian
APT_MIRROR_RASPBERRYPI=${RPI_MIRROR}
DEBIAN_MIRROR=${DEBIAN_MIRROR}
APT_OPTS="${APT_OPTS}"
STAGE_LIST="${PI_GEN_STAGES}"
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

OUT_IMG="${OUTPUT_DIR}/${IMG_NAME}.img.xz"

# Check for already compressed image, or fall back to raw/zip and compress
if compgen -G "deploy/*.img.xz" > /dev/null; then
  cp deploy/*.img.xz "${OUT_IMG}"
elif compgen -G "deploy/*.img" > /dev/null; then
  cp deploy/*.img "${OUT_IMG%.xz}"
  xz -T0 "${OUT_IMG%.xz}"
elif compgen -G "deploy/*.img.zip" > /dev/null; then
  unzip -q deploy/*.img.zip -d deploy
  cp deploy/*.img "${OUT_IMG%.xz}"
  xz -T0 "${OUT_IMG%.xz}"
else
  echo "No image file found in deploy/" >&2
  exit 1
fi

if [ ! -f "${OUT_IMG}" ]; then
  echo "Expected image ${OUT_IMG} not found" >&2
  exit 1
fi

sha256sum "${OUT_IMG}" > "${OUT_IMG}.sha256"
ls -lh "${OUT_IMG}" "${OUT_IMG}.sha256"
echo "Image written to ${OUT_IMG}"
