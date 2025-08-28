#!/usr/bin/env bash
set -euo pipefail

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires Docker, xz, git, sha256sum and roughly 10 GB of free disk space.

for cmd in docker xz git sha256sum; do
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

# Allow reusing a persistent pi-gen checkout for caching purposes.
# When PI_GEN_DIR is provided the directory is not cleaned up and any
# existing clone is re-used; otherwise a temporary directory is created.
PI_GEN_DIR="${PI_GEN_DIR:-}"
if [ -n "$PI_GEN_DIR" ]; then
  mkdir -p "$PI_GEN_DIR"
  WORK_DIR="$PI_GEN_DIR"
else
  WORK_DIR=$(mktemp -d)
  trap 'rm -rf "${WORK_DIR}"' EXIT
fi

PI_GEN_BRANCH="${PI_GEN_BRANCH:-bookworm}"
IMG_NAME="${IMG_NAME:-sugarkube}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}}"
ARM64="${ARM64:-1}"

if [ ! -d "${WORK_DIR}/.git" ]; then
  git clone --depth 1 --branch "${PI_GEN_BRANCH}" \
    https://github.com/RPi-Distro/pi-gen.git "${WORK_DIR}"
else
  git -C "${WORK_DIR}" fetch origin "${PI_GEN_BRANCH}"
  git -C "${WORK_DIR}" reset --hard "origin/${PI_GEN_BRANCH}"
fi
cp "${REPO_ROOT}/scripts/cloud-init/user-data.yaml" \
  "${WORK_DIR}/stage2/01-sys-tweaks/user-data"
cd "${WORK_DIR}"
cat > config <<CFG
IMG_NAME="${IMG_NAME}"
ENABLE_SSH=1
ARM64=${ARM64}
CFG
${SUDO} ./build.sh
mv deploy/*.img "${OUTPUT_DIR}/${IMG_NAME}.img"
xz -T0 "${OUTPUT_DIR}/${IMG_NAME}.img"
sha256sum "${OUTPUT_DIR}/${IMG_NAME}.img.xz" > \
  "${OUTPUT_DIR}/${IMG_NAME}.img.xz.sha256"
ls -lh "${OUTPUT_DIR}/${IMG_NAME}.img.xz" \
  "${OUTPUT_DIR}/${IMG_NAME}.img.xz.sha256"
echo "Image written to ${OUTPUT_DIR}/${IMG_NAME}.img.xz"
