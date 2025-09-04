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
SKIP_BINFMT="${SKIP_BINFMT:-0}"
if [ "$SKIP_BINFMT" -ne 1 ]; then
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
else
  echo "Skipping binfmt handler installation"
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
CLOUD_INIT_DIR="${CLOUD_INIT_DIR:-${REPO_ROOT}/scripts/cloud-init}"
CLOUD_INIT_PATH="${CLOUD_INIT_PATH:-${CLOUD_INIT_DIR}/user-data.yaml}"
CLOUDFLARED_COMPOSE_PATH="${CLOUDFLARED_COMPOSE_PATH:-${CLOUD_INIT_DIR}/docker-compose.cloudflared.yml}"
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
if [ ! -f "${CLOUDFLARED_COMPOSE_PATH}" ]; then
  echo "Cloudflared compose file not found: ${CLOUDFLARED_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -s "${CLOUDFLARED_COMPOSE_PATH}" ]; then
  echo "Cloudflared compose file is empty: ${CLOUDFLARED_COMPOSE_PATH}" >&2
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
if [ "$ARM64" -eq 1 ]; then
  ARMHF=0
else
  ARMHF=1
fi
# Default to the bookworm release branch; architecture is controlled via config.
PI_GEN_BRANCH="${PI_GEN_BRANCH:-bookworm}"
IMG_NAME="${IMG_NAME:-sugarkube}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}}"
mkdir -p "${OUTPUT_DIR}"
export OUTPUT_DIR
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

install -Dm644 "${CLOUDFLARED_COMPOSE_PATH}" \
  "${WORK_DIR}/pi-gen/stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml"

# Bundle pi_node_verifier and optionally clone repos into the image
install -Dm755 "${REPO_ROOT}/scripts/pi_node_verifier.sh" \
  "${WORK_DIR}/pi-gen/stage2/02-sugarkube-tools/files/usr/local/sbin/pi_node_verifier.sh"

CLONE_SUGARKUBE="${CLONE_SUGARKUBE:-false}"
CLONE_TOKEN_PLACE="${CLONE_TOKEN_PLACE:-true}"
CLONE_DSPACE="${CLONE_DSPACE:-true}"
EXTRA_REPOS="${EXTRA_REPOS:-}"

run_sh="${WORK_DIR}/pi-gen/stage2/02-sugarkube-tools/00-run-chroot.sh"
{
  echo "#!/usr/bin/env bash"
  echo "set -euo pipefail"
  if [[ "$CLONE_SUGARKUBE" == "true" || "$CLONE_TOKEN_PLACE" == "true" || "$CLONE_DSPACE" == "true" || -n "$EXTRA_REPOS" ]]; then
    echo "apt-get update"
    echo "apt-get install -y git"
    echo "install -d /opt/projects"
    echo "cd /opt/projects"
    [[ "$CLONE_SUGARKUBE" == "true" ]] && echo "git clone --depth 1 https://github.com/futuroptimist/sugarkube.git"
    [[ "$CLONE_TOKEN_PLACE" == "true" ]] && echo "git clone --depth 1 https://github.com/futuroptimist/token.place.git"
    [[ "$CLONE_DSPACE" == "true" ]] && echo "git clone --depth 1 --branch v3 https://github.com/democratizedspace/dspace.git"
    if [[ -n "$EXTRA_REPOS" ]]; then
      for repo in $EXTRA_REPOS; do
        echo "git clone --depth 1 $repo"
      done
    fi
    echo "chown -R pi:pi /opt/projects"
  else
    echo 'echo "no optional repositories selected; skipping clones"'
  fi
} > "$run_sh"
chmod +x "$run_sh"

cd "${WORK_DIR}/pi-gen"
export DEBIAN_FRONTEND=noninteractive

# Allow callers to override the build timeout
BUILD_TIMEOUT="${BUILD_TIMEOUT:-4h}"

APT_RETRIES="${APT_RETRIES:-5}"
APT_TIMEOUT="${APT_TIMEOUT:-30}"
APT_OPTS="-o Acquire::Retries=${APT_RETRIES} -o Acquire::http::Timeout=${APT_TIMEOUT} \
-o Acquire::https::Timeout=${APT_TIMEOUT} -o Acquire::http::NoCache=true"
APT_OPTS+=" -o APT::Install-Recommends=false -o APT::Install-Suggests=false"

# --- Reliability hooks: mirror rewrites and proxy exceptions ---
# 1) Persistent apt/dpkg Pre-Invoke hook to rewrite ANY raspbian host to FCIX
mkdir -p stage0/00-configure-apt/files/usr/local/sbin
cat > stage0/00-configure-apt/files/usr/local/sbin/apt-rewrite-mirrors <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
target="https://mirror.fcix.net/raspbian/raspbian"
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
done
EOSH
chmod +x stage0/00-configure-apt/files/usr/local/sbin/apt-rewrite-mirrors
mkdir -p stage0/00-configure-apt/files/etc/apt/apt.conf.d
cat > stage0/00-configure-apt/files/etc/apt/apt.conf.d/10-rewrite-mirrors <<'EOC'
APT::Update::Pre-Invoke { "/usr/bin/env bash -lc '/usr/local/sbin/apt-rewrite-mirrors'"; };
DPkg::Pre-Invoke { "/usr/bin/env bash -lc '/usr/local/sbin/apt-rewrite-mirrors'"; };
EOC

# 2) Bypass proxy caches for archive.raspberrypi.com to avoid intermittent 503s
cat > stage0/00-configure-apt/files/etc/apt/apt.conf.d/90-proxy-exceptions <<'EOP'
Acquire::http::Proxy::archive.raspberrypi.com "DIRECT";
Acquire::https::Proxy::archive.raspberrypi.com "DIRECT";
EOP

# 3) Early rewrite before default 00-run.sh executes in stage0
mkdir -p stage0/00-configure-apt
cat > stage0/00-configure-apt/00-run-00-pre.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
target="https://mirror.fcix.net/raspbian/raspbian"
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
done
EOSH
chmod +x stage0/00-configure-apt/00-run-00-pre.sh

# 4) Stage2 safeguard rewrite
mkdir -p stage2/00-configure-apt
cat > stage2/00-configure-apt/01-run.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
target="https://mirror.fcix.net/raspbian/raspbian"
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
done
apt-get -o Acquire::Retries=10 update || true
EOSH
chmod +x stage2/00-configure-apt/01-run.sh

# 5) Export-image post-rewrite after 02-set-sources resets lists
mkdir -p export-image/02-set-sources
cat > export-image/02-set-sources/02-run.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
target="https://mirror.fcix.net/raspbian/raspbian"
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
done
apt-get -o Acquire::Retries=10 update || true
EOSH
chmod +x export-image/02-set-sources/02-run.sh

cat > config <<CFG
IMG_NAME="${IMG_NAME}"
ENABLE_SSH=1
ARM64=${ARM64}
ARMHF=${ARMHF}
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

echo "[sugarkube] Starting pi-gen build (bash path)..."
# Stream output line-by-line so GitHub Actions shows progress and doesn't appear to hang
${SUDO} stdbuf -oL -eL timeout "${BUILD_TIMEOUT}" ./build.sh
echo "[sugarkube] pi-gen build finished"

# Ensure a pi-gen Docker image exists and is tagged for caching
if ! docker image inspect pi-gen:latest >/dev/null 2>&1; then
  img_id=$(docker images --format '{{.Repository}} {{.ID}}' | awk '$1=="pi-gen"{print $2; exit}')
  if [ -n "${img_id}" ]; then
    ${SUDO} docker image tag "${img_id}" pi-gen:latest
  else
    echo "pi-gen Docker image not found" >&2
    exit 1
  fi
fi

if ! docker image inspect pi-gen:latest >/dev/null 2>&1; then
  echo "pi-gen Docker image not found" >&2
  exit 1
fi

OUT_IMG="${OUTPUT_DIR}/${IMG_NAME}.img.xz"

bash "${REPO_ROOT}/scripts/collect_pi_image.sh" "deploy" "${OUT_IMG}"
if [ ! -s "${OUT_IMG}" ]; then
  echo "Output image not found or empty: ${OUT_IMG}" >&2
  exit 1
fi
echo "[sugarkube] Image written to ${OUT_IMG}"
