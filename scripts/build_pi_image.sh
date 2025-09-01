#!/usr/bin/env bash
set -euo pipefail

REQUIRED_SPACE_GB="${REQUIRED_SPACE_GB:-10}"

check_space() {
  local dir="$1"
  local avail_kb required_kb avail_gb
  avail_kb=$(df -Pk "$dir" | awk 'NR==2 {print $4}')
  required_kb=$((REQUIRED_SPACE_GB * 1024 * 1024))
  if [ "$avail_kb" -lt "$required_kb" ]; then
    avail_gb=$(awk "BEGIN {printf \"%.2f\", $avail_kb/1024/1024}")
    echo "Need at least ${REQUIRED_SPACE_GB}GB free in $dir (only ${avail_gb}GB available)" >&2
    exit 1
  fi
}

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires curl, docker, git, sha256sum, stdbuf, timeout, xz, bsdtar and roughly
# 10 GB of free disk space. Set PI_GEN_URL to override the default pi-gen
# repository.

for cmd in curl docker git sha256sum stdbuf timeout xz bsdtar; do
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
if [ ! -s "${CLOUD_INIT_PATH}" ]; then
  echo "Cloud-init file is empty: ${CLOUD_INIT_PATH}" >&2
  exit 1
fi
if ! head -n1 "${CLOUD_INIT_PATH}" | grep -q '^#cloud-config'; then
  echo "Cloud-init file missing #cloud-config header: ${CLOUD_INIT_PATH}" >&2
  exit 1
fi
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

# Ensure temporary and output locations have enough space
check_space "$(dirname "${WORK_DIR}")"

PI_GEN_URL="${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}"
DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://deb.debian.org/debian}"
RPI_MIRROR="${RPI_MIRROR:-https://archive.raspberrypi.com/debian}"
URL_CHECK_TIMEOUT="${URL_CHECK_TIMEOUT:-10}"
for url in "$DEBIAN_MIRROR" "$RPI_MIRROR" "$PI_GEN_URL"; do
  if ! curl -fsIL --connect-timeout "${URL_CHECK_TIMEOUT}" --max-time "${URL_CHECK_TIMEOUT}" "$url" >/dev/null; then
    echo "Cannot reach $url" >&2
    exit 1
  fi
done

ARM64="${ARM64:-1}"
# Use the release branch; architecture is controlled via the config.
PI_GEN_BRANCH="${PI_GEN_BRANCH:-bookworm}"
IMG_NAME="${IMG_NAME:-sugarkube}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}}"
mkdir -p "${OUTPUT_DIR}"
check_space "${OUTPUT_DIR}"

# Build only the minimal lite image by default to keep CI fast
PI_GEN_STAGES="${PI_GEN_STAGES:-stage0 stage1 stage2}"
# Abort early if no stages were requested
if [[ -z "${PI_GEN_STAGES// }" ]]; then
  echo "PI_GEN_STAGES must include at least one stage" >&2
  exit 1
fi

git clone --depth 1 --single-branch --branch "${PI_GEN_BRANCH}" \
  "${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}" \
  "${WORK_DIR}/pi-gen"

USER_DATA="${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/user-data"
cp "${CLOUD_INIT_PATH}" "${USER_DATA}"

# If a TUNNEL_TOKEN_FILE is provided but TUNNEL_TOKEN is not, load it from file
if [ -n "${TUNNEL_TOKEN_FILE:-}" ] && [ -z "${TUNNEL_TOKEN:-}" ]; then
  if [ ! -f "${TUNNEL_TOKEN_FILE}" ]; then
    echo "TUNNEL_TOKEN_FILE not found: ${TUNNEL_TOKEN_FILE}" >&2
    exit 1
  fi
  TUNNEL_TOKEN="$(tr -d '\n' < "${TUNNEL_TOKEN_FILE}")"
fi

# For 32-bit builds, adjust Cloudflare apt source architecture to armhf
if [ "$ARM64" -ne 1 ]; then
  sed -i 's/arch=arm64/arch=armhf/' "${USER_DATA}"
fi

# Embed Cloudflare token if available
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

# Ensure the pi-gen Docker image is tagged for caching
if ! docker image inspect pi-gen:latest >/dev/null 2>&1; then
  img_id=$(docker images --format '{{.Repository}} {{.ID}}' | awk '$1=="pi-gen"{print $2; exit}')
  if [ -n "${img_id}" ]; then
    docker image tag "${img_id}" pi-gen:latest
  else
    echo "pi-gen Docker image not found" >&2
    exit 1
  fi
fi

OUT_IMG="${OUTPUT_DIR}/${IMG_NAME}.img.xz"

bash "${REPO_ROOT}/scripts/collect_pi_image.sh" "deploy" "${OUT_IMG}"
echo "Image written to ${OUT_IMG}"
