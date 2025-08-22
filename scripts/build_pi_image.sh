#!/usr/bin/env bash
set -euo pipefail

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires Docker, git, xz and roughly 10 GB of free disk space.

for cmd in docker git xz; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd is required" >&2
    exit 1
  fi
done

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
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

PI_GEN_BRANCH="${PI_GEN_BRANCH:-bookworm}"
git clone --depth 1 --branch "${PI_GEN_BRANCH}" \
  https://github.com/RPi-Distro/pi-gen.git "${WORK_DIR}/pi-gen"
cp "${REPO_ROOT}/scripts/cloud-init/user-data.yaml" \
  "${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/user-data"
cd "${WORK_DIR}/pi-gen"
cat > config <<'CFG'
IMG_NAME="sugarkube"
ENABLE_SSH=1
CFG
${SUDO} ./build.sh
mv deploy/*.img "${REPO_ROOT}/sugarkube.img"
xz -T0 "${REPO_ROOT}/sugarkube.img"
ls -lh "${REPO_ROOT}/sugarkube.img.xz"
echo "Image written to ${REPO_ROOT}/sugarkube.img.xz"
