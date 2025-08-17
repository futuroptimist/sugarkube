#!/usr/bin/env bash
set -euo pipefail

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires Docker and roughly 10 GB of free disk space.

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT

git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git "${WORK_DIR}/pi-gen"
cp "${REPO_ROOT}/scripts/cloud-init/user-data.yaml" \
  "${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/user-data"
cd "${WORK_DIR}/pi-gen"
cat > config <<'CFG'
IMG_NAME="sugarkube"
ENABLE_SSH=1
CFG
sudo ./build.sh
mv deploy/*.img "${REPO_ROOT}/sugarkube.img"
ls -lh "${REPO_ROOT}/sugarkube.img"
echo "Image written to ${REPO_ROOT}/sugarkube.img"
