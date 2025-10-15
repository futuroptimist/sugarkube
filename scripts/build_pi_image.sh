#!/usr/bin/env bash
set -euo pipefail

if [[ "${DEBUG:-0}" == "1" ]]; then
  set -x
fi

usage() {
  cat <<'EOF'
Usage: build_pi_image.sh [--help]

Build a Raspberry Pi OS image preloaded with cloud-init.

Environment variables:
  CLOUD_INIT_PATH   Path to cloud-init user-data (default scripts/cloud-init/user-data.yaml)
  OUTPUT_DIR        Directory to write the image (default repo root)
  IMG_NAME          Name for the output image (default sugarkube)
  PI_GEN_SOURCE_DIR Path to an existing pi-gen checkout to copy instead of cloning
  TOKEN_PLACE_BRANCH Branch of token.place to clone (default main)
  DSPACE_BRANCH     Branch of dspace to clone (default v3)

See docs/pi_image_cloudflare.md for details.
EOF
}

if [[ "${1:-}" =~ ^(-h|--help)$ ]]; then
  usage
  exit 0
fi

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

ensure_packages() {
  local packages_file="$1"
  shift || true
  if [ ! -d "$(dirname "$packages_file")" ]; then
    mkdir -p "$(dirname "$packages_file")"
  fi
  touch "$packages_file"
  for pkg in "$@"; do
    if [ -n "$pkg" ] && ! grep -qxF "$pkg" "$packages_file"; then
      echo "$pkg" >>"$packages_file"
    fi
  done
}

# Build a Raspberry Pi OS image with cloud-init files preloaded.
# Requires curl, docker, git, sha256sum, stdbuf, timeout, xz, bsdtar, df and roughly
# 10 GB of free disk space. Set PI_GEN_URL to override the default pi-gen repository.

for cmd in curl docker git sha256sum stdbuf timeout xz bsdtar df python3; do
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
ensure_git_safe_directory() {
  local repo="$1"
  # Running as root against a workspace owned by another user (like GitHub's runner)
  # triggers Git's "dubious ownership" guard unless the path is marked safe.
  if git config --system --add safe.directory "$repo" >/dev/null 2>&1; then
    return 0
  fi
  if git config --global --add safe.directory "$repo" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}
if [ "$(id -u)" -eq 0 ]; then
  if ! ensure_git_safe_directory "${REPO_ROOT}"; then
    echo "warning: failed to register ${REPO_ROOT} as a safe Git directory" >&2
  fi
fi
REPO_COMMIT="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
REPO_REF="${GITHUB_REF:-$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || "unknown")}"
RUNNER_OS_VALUE="${RUNNER_OS:-$(uname -s)}"
RUNNER_ARCH_VALUE="${RUNNER_ARCH:-$(uname -m)}"
CLOUD_INIT_DIR="${CLOUD_INIT_DIR:-${REPO_ROOT}/scripts/cloud-init}"
CLOUD_INIT_PATH="${CLOUD_INIT_PATH:-${CLOUD_INIT_DIR}/user-data.yaml}"
CLOUDFLARED_COMPOSE_PATH="${CLOUDFLARED_COMPOSE_PATH:-${CLOUD_INIT_DIR}/docker-compose.cloudflared.yml}"
PROJECTS_COMPOSE_PATH="${PROJECTS_COMPOSE_PATH:-${CLOUD_INIT_DIR}/docker-compose.yml}"
START_PROJECTS_PATH="${START_PROJECTS_PATH:-${CLOUD_INIT_DIR}/start-projects.sh}"
INIT_ENV_PATH="${INIT_ENV_PATH:-${CLOUD_INIT_DIR}/init-env.sh}"
EXPORT_KUBECONFIG_PATH="${EXPORT_KUBECONFIG_PATH:-${CLOUD_INIT_DIR}/export-kubeconfig.sh}"
EXPORT_NODE_TOKEN_PATH="${EXPORT_NODE_TOKEN_PATH:-${CLOUD_INIT_DIR}/export-node-token.sh}"
K3S_READY_PATH="${K3S_READY_PATH:-${CLOUD_INIT_DIR}/k3s-ready.sh}"
APPLY_HELM_BUNDLES_PATH="${APPLY_HELM_BUNDLES_PATH:-${CLOUD_INIT_DIR}/apply-helm-bundles.sh}"

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

# Validate cloud-init YAML syntax when PyYAML is available
SKIP_CLOUD_INIT_VALIDATION="${SKIP_CLOUD_INIT_VALIDATION:-0}"
if [ "${SKIP_CLOUD_INIT_VALIDATION}" -ne 1 ]; then
  if command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" >/dev/null 2>&1; then
    if ! python3 - "${CLOUD_INIT_PATH}" <<'PY' >/dev/null 2>&1
import sys, yaml
with open(sys.argv[1]) as f:
    yaml.safe_load(f)
PY
    then
      echo "Cloud-init file contains invalid YAML: ${CLOUD_INIT_PATH}" >&2
      exit 1
    fi
  else
    echo "PyYAML not installed; skipping cloud-init YAML validation" >&2
  fi
else
  echo "Skipping cloud-init YAML validation"
fi

if [ ! -f "${CLOUDFLARED_COMPOSE_PATH}" ]; then
  echo "Cloudflared compose file not found: ${CLOUDFLARED_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -s "${CLOUDFLARED_COMPOSE_PATH}" ]; then
  echo "Cloudflared compose file is empty: ${CLOUDFLARED_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -f "${PROJECTS_COMPOSE_PATH}" ]; then
  echo "Projects compose file not found: ${PROJECTS_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -s "${PROJECTS_COMPOSE_PATH}" ]; then
  echo "Projects compose file is empty: ${PROJECTS_COMPOSE_PATH}" >&2
  exit 1
fi
if [ ! -f "${START_PROJECTS_PATH}" ]; then
  echo "Start projects script not found: ${START_PROJECTS_PATH}" >&2
  exit 1
fi
if [ ! -s "${START_PROJECTS_PATH}" ]; then
  echo "Start projects script is empty: ${START_PROJECTS_PATH}" >&2
  exit 1
fi
if [ ! -f "${INIT_ENV_PATH}" ]; then
  echo "Init env script not found: ${INIT_ENV_PATH}" >&2
  exit 1
fi
if [ ! -s "${INIT_ENV_PATH}" ]; then
  echo "Init env script is empty: ${INIT_ENV_PATH}" >&2
  exit 1
fi
if [ ! -f "${K3S_READY_PATH}" ]; then
  echo "k3s readiness script not found: ${K3S_READY_PATH}" >&2
  exit 1
fi
if [ ! -s "${K3S_READY_PATH}" ]; then
  echo "k3s readiness script is empty: ${K3S_READY_PATH}" >&2
  exit 1
fi
if [ ! -f "${EXPORT_KUBECONFIG_PATH}" ]; then
  echo "Export kubeconfig script not found: ${EXPORT_KUBECONFIG_PATH}" >&2
  exit 1
fi
if [ ! -s "${EXPORT_KUBECONFIG_PATH}" ]; then
  echo "Export kubeconfig script is empty: ${EXPORT_KUBECONFIG_PATH}" >&2
  exit 1
fi

KEEP_WORK_DIR="${KEEP_WORK_DIR:-0}"
WORK_DIR=$(mktemp -d)
cleanup() {
  if [[ "${KEEP_WORK_DIR}" != "1" ]]; then
    rm -rf "${WORK_DIR}"
  else
    echo "[sugarkube] KEEP_WORK_DIR=1; leaving work dir: ${WORK_DIR}"
  fi
}
trap cleanup EXIT

# Ensure temporary and output locations have enough space
check_space "$(dirname "${WORK_DIR}")"

PI_GEN_URL="${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}"
DEBIAN_MIRROR="${DEBIAN_MIRROR:-https://deb.debian.org/debian}"
RPI_MIRROR="${RPI_MIRROR:-https://archive.raspberrypi.com/debian}"
URL_CHECK_TIMEOUT="${URL_CHECK_TIMEOUT:-10}"
SKIP_URL_CHECK="${SKIP_URL_CHECK:-0}"
is_http_url() {
  local candidate="$1"
  [[ "$candidate" =~ ^https?:// ]]
}
if [ "$SKIP_URL_CHECK" -ne 1 ]; then
  for url in "$DEBIAN_MIRROR" "$RPI_MIRROR" "$PI_GEN_URL"; do
    if [ -z "$url" ]; then
      continue
    fi
    if ! is_http_url "$url"; then
      echo "Skipping reachability check for non-HTTP(S) source: $url"
      continue
    fi
    if ! curl -fsIL --connect-timeout "${URL_CHECK_TIMEOUT}" --max-time "${URL_CHECK_TIMEOUT}" "$url" >/dev/null; then
      echo "Cannot reach $url" >&2
      exit 1
    fi
  done
else
  echo "Skipping URL reachability checks"
fi

ARM64="${ARM64:-1}"
if [ "$ARM64" -eq 1 ]; then
  ARMHF=0
else
  ARMHF=1
fi
DEFAULT_PI_GEN_BRANCH="bookworm"
PI_GEN_SOURCE_DIR="${PI_GEN_SOURCE_DIR:-}"
PI_GEN_BRANCH="${PI_GEN_BRANCH:-}"
IMG_NAME="${IMG_NAME:-sugarkube}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}}"
mkdir -p "${OUTPUT_DIR}"
OUT_IMG="${OUTPUT_DIR}/${IMG_NAME}.img.xz"
BUILD_LOG="${OUTPUT_DIR}/${IMG_NAME}.build.log"
: >"${BUILD_LOG}"
# Abort to avoid clobbering existing images unless FORCE_OVERWRITE=1
if [ -e "${OUT_IMG}" ] && [ "${FORCE_OVERWRITE:-0}" -ne 1 ]; then
  echo "Output image already exists: ${OUT_IMG} (set FORCE_OVERWRITE=1 to overwrite)" >&2
  exit 1
fi
export OUTPUT_DIR
check_space "${OUTPUT_DIR}"

# Build only the minimal lite image by default to keep CI fast
PI_GEN_STAGES="${PI_GEN_STAGES:-stage0 stage1 stage2}"
# Abort early if no stages were requested
if [[ -z "${PI_GEN_STAGES// }" ]]; then
  echo "PI_GEN_STAGES must include at least one stage" >&2
  exit 1
fi

PI_GEN_DIR="${WORK_DIR}/pi-gen"
if [ -n "${PI_GEN_SOURCE_DIR}" ]; then
  if [ ! -d "${PI_GEN_SOURCE_DIR}" ]; then
    echo "pi-gen source directory not found: ${PI_GEN_SOURCE_DIR}" >&2
    exit 1
  fi
  if [ ! -f "${PI_GEN_SOURCE_DIR}/build.sh" ]; then
    echo "pi-gen source directory missing build.sh: ${PI_GEN_SOURCE_DIR}" >&2
    exit 1
  fi
  echo "[sugarkube] Using existing pi-gen checkout from ${PI_GEN_SOURCE_DIR}"
  mkdir -p "${PI_GEN_DIR}"
  cp -a "${PI_GEN_SOURCE_DIR}/." "${PI_GEN_DIR}/"
  if git -C "${PI_GEN_SOURCE_DIR}" rev-parse HEAD >/dev/null 2>&1; then
    PI_GEN_COMMIT="$(git -C "${PI_GEN_SOURCE_DIR}" rev-parse HEAD)"
    if [ -z "${PI_GEN_BRANCH}" ]; then
      if branch_detected=$(git -C "${PI_GEN_SOURCE_DIR}" \
        rev-parse --abbrev-ref HEAD 2>/dev/null); then
        PI_GEN_BRANCH="${branch_detected}"
      else
        PI_GEN_BRANCH="local"
      fi
    fi
  else
    PI_GEN_COMMIT="local-copy"
    if [ -z "${PI_GEN_BRANCH}" ]; then
      PI_GEN_BRANCH="local"
    fi
  fi
else
  PI_GEN_BRANCH="${PI_GEN_BRANCH:-${DEFAULT_PI_GEN_BRANCH}}"
  git clone --depth 1 --single-branch --branch "${PI_GEN_BRANCH}" \
    "${PI_GEN_URL:-https://github.com/RPi-Distro/pi-gen.git}" \
    "${PI_GEN_DIR}"
  PI_GEN_COMMIT="$(git -C "${PI_GEN_DIR}" rev-parse HEAD)"
fi

PI_GEN_BRANCH="${PI_GEN_BRANCH:-${DEFAULT_PI_GEN_BRANCH}}"

USER_DATA="${PI_GEN_DIR}/stage2/01-sys-tweaks/user-data"
cp "${CLOUD_INIT_PATH}" "${USER_DATA}"

ensure_packages "${PI_GEN_DIR}/stage2/01-sys-tweaks/00-packages" \
  policykit-1

just_path_profile="${PI_GEN_DIR}/stage2/01-sys-tweaks/files/etc/profile.d/sugarkube-path.sh"
install -d "$(dirname "${just_path_profile}")"
cat >"${just_path_profile}" <<'EOSH'
# Ensure /usr/local bin directories stay ahead of system paths for both pi and root users.
case ":${PATH}:" in
  *:/usr/local/bin:*) ;;
  *)
    PATH="/usr/local/bin:${PATH}"
    ;;
esac
case ":${PATH}:" in
  *:/usr/local/sbin:*) ;;
  *)
    PATH="/usr/local/sbin:${PATH}"
    ;;
esac
export PATH
EOSH

just_install_dir="${PI_GEN_DIR}/stage2/01-sys-tweaks"
install -d "${just_install_dir}"
just_install_script="${just_install_dir}/03-run-chroot.sh"
cat >"${just_install_script}" <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail

APT_RETRIES=${APT_RETRIES:-5}
APT_TIMEOUT=${APT_TIMEOUT:-30}
APT_OPTS=(
  -o Acquire::Retries="${APT_RETRIES}"
  -o Acquire::http::Timeout="${APT_TIMEOUT}"
  -o Acquire::https::Timeout="${APT_TIMEOUT}"
  -o Acquire::http::NoCache=true
  -o APT::Get::Fix-Missing=true
  -o APT::Install-Recommends=false
  -o APT::Install-Suggests=false
)

ensure_profile_path() {
  local profile="$1"
  if [ -f "${profile}" ] && ! grep -q '/usr/local/bin' "${profile}"; then
    {
      printf '\n# Added by sugarkube build to keep just available in PATH\n'
      printf 'export PATH="/usr/local/bin:$PATH"\n'
    } >>"${profile}"
  fi
}

ensure_profile_path "/home/pi/.profile"
ensure_profile_path "/root/.profile"

mkdir -p /etc/profile.d
cat >/etc/profile.d/sugarkube-path.sh <<'EOF'
case ":${PATH}:" in
  *:/usr/local/bin:*) ;;
  *) PATH="/usr/local/bin:${PATH}" ;;
esac
case ":${PATH}:" in
  *:/usr/local/sbin:*) ;;
  *) PATH="/usr/local/sbin:${PATH}" ;;
esac
export PATH
EOF

if ! command -v just >/dev/null 2>&1; then
  apt_failed=0
  if command -v apt-get >/dev/null 2>&1; then
    if ! apt-get "${APT_OPTS[@]}" update; then
      apt_failed=1
    elif ! apt-get "${APT_OPTS[@]}" install -y --no-install-recommends just; then
      apt_failed=1
    fi
  else
    apt_failed=1
  fi

  if ! command -v just >/dev/null 2>&1; then
    if [ "${apt_failed}" -ne 0 ]; then
      echo "apt-get failed to install just; using upstream installer" >&2
    fi
    if ! curl -fsSL https://just.systems/install.sh | bash -s -- --to /usr/local/bin; then
      echo "Failed to install just" >&2
      exit 1
    fi
  fi
fi

log_build() {
  local log_target="${BUILD_LOG:-${LOG_FILE:-}}"
  if [ -n "${log_target}" ] && [ -d "$(dirname "${log_target}")" ]; then
    if ! printf '%s\n' "$1" | tee -a "${log_target}"; then
      printf '%s\n' "$1"
    fi
  else
    printf '%s\n' "$1"
  fi
}

just_path=$(command -v just || true)
if [ -z "${just_path}" ]; then
  echo "just not found after installation attempts" >&2
  exit 1
fi

log_build "[sugarkube] just command verified at ${just_path}"
just_version=$(just --version 2>&1 | head -n1 || true)
if [ -n "${just_version}" ]; then
  log_build "[sugarkube] just version: ${just_version}"
fi

if [ -f /opt/sugarkube/justfile ]; then
  if su - pi -c 'cd /opt/sugarkube && PATH="/usr/local/bin:$PATH" just --list >/tmp/sugarkube-just-list.txt'; then
    rm -f /tmp/sugarkube-just-list.txt
    printf '[sugarkube] Verified just --list for /opt/sugarkube justfile\n'
  else
    echo 'just --list failed for /opt/sugarkube' >&2
    exit 1
  fi
fi
EOSH
chmod +x "${just_install_script}"

# Provide compatibility symlinks for both historical paths and the canonical name.
ln -sf "03-run-chroot.sh" "${just_install_dir}/03-run.sh"
ln -sf "03-run-chroot.sh" "${just_install_dir}/03-run-chroot-just.sh"

# If a TUNNEL_TOKEN_FILE is provided but TUNNEL_TOKEN is not, load it from file
if [ -n "${TUNNEL_TOKEN_FILE:-}" ] && [ -z "${TUNNEL_TOKEN:-}" ]; then
  if [ ! -f "${TUNNEL_TOKEN_FILE}" ]; then
    echo "TUNNEL_TOKEN_FILE not found: ${TUNNEL_TOKEN_FILE}" >&2
    exit 1
  fi
  token_from_file="$(tr -d '\r\n' < "${TUNNEL_TOKEN_FILE}")"
  printf -v TUNNEL_TOKEN '%s' "${token_from_file}"
fi

# For 32-bit builds, adjust Cloudflare apt source architecture to armhf
if [ "$ARM64" -ne 1 ]; then
  sed -i 's/arch=arm64/arch=armhf/' "${USER_DATA}"
fi

# Embed Cloudflare token if available
if [ -n "${TUNNEL_TOKEN:-}" ]; then
  echo "Embedding Cloudflare token into cloud-init"
  escaped_token=$(printf '%s\n' "${TUNNEL_TOKEN}" | sed -e 's/[\/&]/\\&/g')
  sed -i "s|TUNNEL_TOKEN=\"\"|TUNNEL_TOKEN=\"${escaped_token}\"|" "${USER_DATA}"
fi


# Bundle pi_node_verifier and optionally clone repos into the image
install -Dm755 "${REPO_ROOT}/scripts/pi_node_verifier.sh" \
  "${PI_GEN_DIR}/stage2/02-sugarkube-tools/files/usr/local/sbin/pi_node_verifier.sh"

install -Dm755 "${REPO_ROOT}/scripts/first_boot_service.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/first_boot_service.py"

install -Dm755 "${REPO_ROOT}/scripts/self_heal_service.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/self_heal_service.py"

install -Dm755 "${REPO_ROOT}/scripts/ssd_clone.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/ssd_clone.py"

install -Dm755 "${REPO_ROOT}/scripts/ssd_clone_service.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/ssd_clone_service.py"

install -Dm755 "${REPO_ROOT}/scripts/sugarkube_teams.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/sugarkube_teams.py"

install -Dm755 "${REPO_ROOT}/scripts/sugarkube_teams.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/usr/local/bin/sugarkube-teams"

install -Dm644 "${REPO_ROOT}/scripts/systemd/first-boot.service" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/etc/systemd/system/first-boot.service"

install -Dm644 "${REPO_ROOT}/scripts/systemd/ssd-clone.service" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/etc/systemd/system/ssd-clone.service"

install -d "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/etc/systemd/system/multi-user.target.wants"
ln -sf ../first-boot.service \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/etc/systemd/system/multi-user.target.wants/first-boot.service"


install -Dm644 "${REPO_ROOT}/scripts/udev/99-sugarkube-ssd-clone.rules" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/etc/udev/rules.d/99-sugarkube-ssd-clone.rules"

install -Dm755 "${EXPORT_KUBECONFIG_PATH}" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/export-kubeconfig.sh"

install -Dm755 "${EXPORT_NODE_TOKEN_PATH}" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/export-node-token.sh"

install -Dm755 "${APPLY_HELM_BUNDLES_PATH}" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/apply-helm-bundles.sh"

install -Dm755 "${K3S_READY_PATH}" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/k3s-ready.sh"
install -Dm755 "${REPO_ROOT}/scripts/token_place_replay_samples.py" \
  "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/token_place_replay_samples.py"

TOKEN_PLACE_SAMPLES_SRC="${REPO_ROOT}/samples/token_place"
TOKEN_PLACE_SAMPLES_DEST="${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/sugarkube/samples/token-place"
if [ -d "${TOKEN_PLACE_SAMPLES_SRC}" ]; then
  rm -rf "${TOKEN_PLACE_SAMPLES_DEST}"
  mkdir -p "${TOKEN_PLACE_SAMPLES_DEST}"
  cp -a "${TOKEN_PLACE_SAMPLES_SRC}/." "${TOKEN_PLACE_SAMPLES_DEST}/"
fi

CLONE_SUGARKUBE="${CLONE_SUGARKUBE:-false}"
CLONE_TOKEN_PLACE="${CLONE_TOKEN_PLACE:-true}"
CLONE_DSPACE="${CLONE_DSPACE:-true}"
EXTRA_REPOS="${EXTRA_REPOS:-}"
TOKEN_PLACE_BRANCH="${TOKEN_PLACE_BRANCH:-main}"
DSPACE_BRANCH="${DSPACE_BRANCH:-v3}"

# Prepare compose file for token.place and dspace; drop services when skipped
PROJECTS_COMPOSE_TEMP="${WORK_DIR}/docker-compose.yml"
cp "${PROJECTS_COMPOSE_PATH}" "${PROJECTS_COMPOSE_TEMP}"
if [[ "$CLONE_TOKEN_PLACE" != "true" ]]; then
  sed -i '/# tokenplace-start/,/# tokenplace-end/d' "${PROJECTS_COMPOSE_TEMP}"
fi
if [[ "$CLONE_DSPACE" != "true" ]]; then
  sed -i '/# dspace-start/,/# dspace-end/d' "${PROJECTS_COMPOSE_TEMP}"
fi
if [[ "$CLONE_TOKEN_PLACE" != "true" && "$CLONE_DSPACE" != "true" && -z "$EXTRA_REPOS" ]]; then
  sed -i '/# projects-start/,/# projects-end/d' "${USER_DATA}"
  sed -i '/# projects-runcmd/d' "${USER_DATA}"
else
  install -Dm644 "${PROJECTS_COMPOSE_TEMP}" \
    "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/docker-compose.yml"
  install -Dm755 "${START_PROJECTS_PATH}" \
    "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/start-projects.sh"
  install -Dm755 "${INIT_ENV_PATH}" \
    "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/init-env.sh"
  install -Dm644 "${REPO_ROOT}/scripts/cloud-init/observability/grafana-agent.river" \
    "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/observability/grafana-agent.river"
  install -Dm644 "${REPO_ROOT}/scripts/cloud-init/observability/grafana-agent.env.example" \
    "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/observability/grafana-agent.env.example"
  install -Dm644 "${REPO_ROOT}/scripts/cloud-init/observability/netdata.env.example" \
    "${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/observability/netdata.env.example"
  if [[ "$CLONE_TOKEN_PLACE" == "true" && -d "${TOKEN_PLACE_SAMPLES_SRC}" ]]; then
    token_place_samples_project="${PI_GEN_DIR}/stage2/01-sys-tweaks/files/opt/projects/token.place/samples"
    rm -rf "${token_place_samples_project}"
    mkdir -p "${token_place_samples_project}"
    cp -a "${TOKEN_PLACE_SAMPLES_SRC}/." "${token_place_samples_project}/"
  fi
fi

run_sh="${PI_GEN_DIR}/stage2/02-sugarkube-tools/00-run-chroot.sh"
cat >"$run_sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

CLONE_SUGARKUBE="__CLONE_SUGARKUBE__"
CLONE_TOKEN_PLACE="__CLONE_TOKEN_PLACE__"
CLONE_DSPACE="__CLONE_DSPACE__"
EXTRA_REPOS="__EXTRA_REPOS__"
TOKEN_PLACE_BRANCH="__TOKEN_PLACE_BRANCH__"
DSPACE_BRANCH="__DSPACE_BRANCH__"

warn() {
  printf 'warning: %s\n' "$1" >&2
}

clone_into_projects() {
  local name="$1"
  local url="$2"
  local branch="${3:-}"
  local dest="/opt/projects/$name"

  if [[ -d "$dest/.git" ]]; then
    echo "repo $name already present at $dest; skipping clone"
    return 0
  fi

  local -a cmd=(git clone --depth 1)
  if [[ -n "$branch" ]]; then
    cmd+=(--branch "$branch")
  fi
  cmd+=("$url" "$dest")

  if "${cmd[@]}"; then
    chown -R pi:pi "$dest"
    echo "cloned $name into $dest"
  else
    warn "failed to clone $name from $url"
    rm -rf "$dest"
  fi
}

sync_repo_to_home() {
  local name="$1"
  local source="/opt/projects/$name"
  local dest="/home/pi/$name"

  if [[ ! -d "$source/.git" ]]; then
    warn "cannot sync $name to /home/pi; source repo missing at $source"
    return 0
  fi

  rm -rf "$dest"
  mkdir -p /home/pi
  cp -a "$source" "$dest"
  chown -R pi:pi "$dest"
  echo "synced $name to $dest"
}

clone_extra_repo() {
  local url="$1"
  [[ -z "$url" ]] && return 0

  local name
  name="${url##*/}"
  name="${name%.git}"
  if [[ -z "$name" ]]; then
    warn "unable to derive repository name from $url"
    return 0
  fi

  local dest="/opt/projects/$name"
  if [[ -d "$dest/.git" ]]; then
    echo "extra repo $name already present at $dest; skipping clone"
    return 0
  fi

  if git clone --depth 1 "$url" "$dest"; then
    chown -R pi:pi "$dest"
    echo "cloned extra repo $url into $dest"
  else
    warn "failed to clone extra repo from $url"
    rm -rf "$dest"
  fi
}

if [[ "$CLONE_SUGARKUBE" != "true" && "$CLONE_TOKEN_PLACE" != "true" && "$CLONE_DSPACE" != "true" && -z "$EXTRA_REPOS" ]]; then
  warn "no optional repositories selected; skipping clones"
  exit 0
fi

apt-get update
apt-get install -y git
install -d -m 755 -o pi -g pi /opt/projects
install -d -m 755 -o pi -g pi /home/pi

if [[ "$CLONE_SUGARKUBE" == "true" ]]; then
  clone_into_projects "sugarkube" "https://github.com/futuroptimist/sugarkube.git"
  sync_repo_to_home "sugarkube"
  if [[ ! -d /home/pi/sugarkube/.git ]]; then
    warn "sugarkube repo missing from /home/pi after clone attempt"
  fi
else
  warn "skipping clone of sugarkube (CLONE_SUGARKUBE=$CLONE_SUGARKUBE)"
fi

if [[ "$CLONE_TOKEN_PLACE" == "true" ]]; then
  clone_into_projects "token.place" "https://github.com/futuroptimist/token.place.git" "$TOKEN_PLACE_BRANCH"
  sync_repo_to_home "token.place"
  if [[ ! -d /home/pi/token.place/.git ]]; then
    warn "token.place repo missing from /home/pi after clone attempt"
  fi
else
  warn "skipping clone of token.place (CLONE_TOKEN_PLACE=$CLONE_TOKEN_PLACE)"
fi

if [[ "$CLONE_DSPACE" == "true" ]]; then
  clone_into_projects "dspace" "https://github.com/democratizedspace/dspace.git" "$DSPACE_BRANCH"
  sync_repo_to_home "dspace"
  if [[ ! -d /home/pi/dspace/.git ]]; then
    warn "dspace repo missing from /home/pi after clone attempt"
  fi
else
  warn "skipping clone of dspace (CLONE_DSPACE=$CLONE_DSPACE)"
fi

if [[ -n "$EXTRA_REPOS" ]]; then
  for repo in $EXTRA_REPOS; do
    clone_extra_repo "$repo"
  done
fi

echo "contents of /home/pi after cloning:"
ls -la /home/pi
EOF

python3 - "$run_sh" "${CLONE_SUGARKUBE}" "${CLONE_TOKEN_PLACE}" "${CLONE_DSPACE}" "${EXTRA_REPOS}" "${TOKEN_PLACE_BRANCH}" "${DSPACE_BRANCH}" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
content = path.read_text()
keys = [
    "__CLONE_SUGARKUBE__",
    "__CLONE_TOKEN_PLACE__",
    "__CLONE_DSPACE__",
    "__EXTRA_REPOS__",
    "__TOKEN_PLACE_BRANCH__",
    "__DSPACE_BRANCH__",
]

for key, value in zip(keys, sys.argv[2:]):
    content = content.replace(key, value)

path.write_text(content)
PY

chmod +x "$run_sh"

cd "${PI_GEN_DIR}"
export DEBIAN_FRONTEND=noninteractive

# Allow callers to override the build timeout
BUILD_TIMEOUT="${BUILD_TIMEOUT:-4h}"

APT_RETRIES="${APT_RETRIES:-5}"
APT_TIMEOUT="${APT_TIMEOUT:-30}"
APT_OPTS="-o Acquire::Retries=${APT_RETRIES} -o Acquire::http::Timeout=${APT_TIMEOUT} \
-o Acquire::https::Timeout=${APT_TIMEOUT} -o Acquire::http::NoCache=true \
-o APT::Get::Fix-Missing=true"
APT_OPTS+=" -o APT::Install-Recommends=false -o APT::Install-Suggests=false"

SKIP_MIRROR_REWRITE="${SKIP_MIRROR_REWRITE:-0}"

DEFAULT_APT_MIRRORS=(
  "https://mirror.fcix.net/raspbian/raspbian"
  "https://mirrors.ocf.berkeley.edu/raspbian/raspbian"
  "https://raspbian.raspberrypi.org/raspbian"
)

if [ -n "${APT_REWRITE_MIRRORS:-}" ]; then
  # shellcheck disable=SC2206
  read -r -a _APT_REWRITE_MIRRORS <<<"${APT_REWRITE_MIRRORS}"
elif [ -n "${APT_REWRITE_MIRROR:-}" ]; then
  _APT_REWRITE_MIRRORS=("${APT_REWRITE_MIRROR}")
else
  _APT_REWRITE_MIRRORS=("${DEFAULT_APT_MIRRORS[@]}")
fi

APT_REWRITE_MIRRORS=()
for mirror in "${_APT_REWRITE_MIRRORS[@]}"; do
  if [ -n "${mirror}" ]; then
    APT_REWRITE_MIRRORS+=("${mirror}")
  fi
done
if [ "${#APT_REWRITE_MIRRORS[@]}" -eq 0 ]; then
  APT_REWRITE_MIRRORS=("${DEFAULT_APT_MIRRORS[@]}")
fi

APT_REWRITE_MIRROR="${APT_REWRITE_MIRRORS[0]}"
APT_MIRROR_ARRAY_CONTENT=$(printf '  "%s"\n' "${APT_REWRITE_MIRRORS[@]}")
MIRROR_STATE_FILE="/var/lib/apt/sugarkube-active-mirror"
export APT_MIRROR_ARRAY_CONTENT MIRROR_STATE_FILE

replace_mirror_placeholders() {
  local target_file="$1"
  python3 - <<'PY' "${target_file}"
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
array = os.environ["APT_MIRROR_ARRAY_CONTENT"].rstrip("\n")
state_file = os.environ["MIRROR_STATE_FILE"]
content = path.read_text()
content = content.replace("__APT_MIRROR_ARRAY__", array)
content = content.replace("__MIRROR_STATE_FILE__", state_file)
path.write_text(content)
PY
}

if [ "$SKIP_MIRROR_REWRITE" -ne 1 ]; then
  # --- Reliability hooks: mirror rewrites and proxy exceptions ---
  mkdir -p stage0/00-configure-apt/files/usr/local/sbin
  cat > stage0/00-configure-apt/files/usr/local/sbin/apt-rewrite-mirrors <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
mirrors=(
__APT_MIRROR_ARRAY__
)
state_file="__MIRROR_STATE_FILE__"
state_dir="$(dirname "$state_file")"
mkdir -p "$state_dir"
target="${mirrors[0]}"
if [ -s "$state_file" ]; then
  while IFS= read -r candidate; do
    for m in "${mirrors[@]}"; do
      if [ "$m" = "$candidate" ]; then
        target="$candidate"
        break 2
      fi
    done
  done < "$state_file"
fi
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
  sed -i -E "s#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#${target}#g" "$f" || true
done
printf '%s\n' "$target" > "$state_file"
EOSH
  replace_mirror_placeholders stage0/00-configure-apt/files/usr/local/sbin/apt-rewrite-mirrors
  chmod +x stage0/00-configure-apt/files/usr/local/sbin/apt-rewrite-mirrors

  mkdir -p stage0/00-configure-apt/files/etc/apt/apt.conf.d
  cat > stage0/00-configure-apt/files/etc/apt/apt.conf.d/10-rewrite-mirrors <<'EOC'
APT::Update::Pre-Invoke { "/usr/bin/env bash -lc '/usr/local/sbin/apt-rewrite-mirrors'"; };
DPkg::Pre-Invoke { "/usr/bin/env bash -lc '/usr/local/sbin/apt-rewrite-mirrors'"; };
EOC

  # Bypass proxy caches for archive.raspberrypi.com to avoid intermittent 503s
  cat > stage0/00-configure-apt/files/etc/apt/apt.conf.d/90-proxy-exceptions <<'EOP'
Acquire::http::Proxy::archive.raspberrypi.com "DIRECT";
Acquire::https::Proxy::archive.raspberrypi.com "DIRECT";
EOP

  mkdir -p stage0/00-configure-apt
  cat > stage0/00-configure-apt/00-run-00-pre.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
mirrors=(
__APT_MIRROR_ARRAY__
)
target="${mirrors[0]}"
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
  sed -i -E "s#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#${target}#g" "$f" || true
done
EOSH
  replace_mirror_placeholders stage0/00-configure-apt/00-run-00-pre.sh
  chmod +x stage0/00-configure-apt/00-run-00-pre.sh

  cat > stage0/00-configure-apt/01-run.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
try_mirrors=(
__APT_MIRROR_ARRAY__
)
APT_OPTS_DEFAULT="-o Acquire::Retries=10 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
state_file="__MIRROR_STATE_FILE__"
mkdir -p "$(dirname "$state_file")"
for m in "${try_mirrors[@]}"; do
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    if [ -f "$f" ]; then
      sed -i "s#https?://[^/\r\n]*/raspbian#${m}#g" "$f" || true
      sed -i -E "s#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#${m}#g" "$f" || true
    fi
  done
  if apt-get $APT_OPTS_DEFAULT update; then
    printf '%s\n' "$m" > "$state_file"
    if apt-get $APT_OPTS_DEFAULT -o Dpkg::Options::="--force-confnew" dist-upgrade -y; then
      exit 0
    fi
    apt-get $APT_OPTS_DEFAULT -o Dpkg::Options::="--force-confnew" dist-upgrade -y --fix-missing || true
    printf '%s\n' "$m" > "$state_file"
  fi
done
echo "All apt mirror attempts failed" >&2
exit 1
EOSH
  replace_mirror_placeholders stage0/00-configure-apt/01-run.sh
  chmod +x stage0/00-configure-apt/01-run.sh

  mkdir -p stage2/00-configure-apt
  cat > stage2/00-configure-apt/01-run.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
try_mirrors=(
__APT_MIRROR_ARRAY__
)
APT_OPTS_DEFAULT="-o Acquire::Retries=10 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
state_file="__MIRROR_STATE_FILE__"
mkdir -p "$(dirname "$state_file")"
for m in "${try_mirrors[@]}"; do
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    if [ -f "$f" ]; then
      sed -i "s#https?://[^/\r\n]*/raspbian#${m}#g" "$f" || true
      sed -i -E "s#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#${m}#g" "$f" || true
    fi
  done
  if apt-get $APT_OPTS_DEFAULT update; then
    printf '%s\n' "$m" > "$state_file"
    break
  fi
done
EOSH
  replace_mirror_placeholders stage2/00-configure-apt/01-run.sh
  chmod +x stage2/00-configure-apt/01-run.sh

  cat > stage2/00-configure-apt/00-run-00-pre.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
mirrors=(
__APT_MIRROR_ARRAY__
)
target="${mirrors[0]}"
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i -E "s#https?://[^/[:space:]]+/raspbian#${target}#g" "$f" || true
  sed -i -E "s#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#${target}#g" "$f" || true
done
EOSH
  replace_mirror_placeholders stage2/00-configure-apt/00-run-00-pre.sh
  chmod +x stage2/00-configure-apt/00-run-00-pre.sh

  mkdir -p export-image/02-set-sources
  cat > export-image/02-set-sources/02-run.sh <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
try_mirrors=(
__APT_MIRROR_ARRAY__
)
state_file="__MIRROR_STATE_FILE__"
mkdir -p "$(dirname "$state_file")"
for m in "${try_mirrors[@]}"; do
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    [ -f "$f" ] || continue
    sed -i "s#https?://[^/\r\n]*/raspbian#${m}#g" "$f" || true
    sed -i -E "s#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#${m}#g" "$f" || true
    sed -i -E "s#http://mirror\\.as43289\\.net/raspbian/raspbian#${m}#g" "$f" || true
  done
  if apt-get -o Acquire::Retries=10 update; then
    printf '%s\n' "$m" > "$state_file"
    break
  fi
done
EOSH
  replace_mirror_placeholders export-image/02-set-sources/02-run.sh
  chmod +x export-image/02-set-sources/02-run.sh
else
  echo "Skipping apt mirror rewrites"
fi

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
BUILD_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
SECONDS=0
# Stream output line-by-line so GitHub Actions shows progress and doesn't appear to hang
${SUDO} stdbuf -oL -eL timeout "${BUILD_TIMEOUT}" ./build.sh
BUILD_DURATION_SECONDS=${SECONDS}
BUILD_COMPLETED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
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

bash "${REPO_ROOT}/scripts/collect_pi_image.sh" "deploy" "${OUT_IMG}"
if [ ! -s "${OUT_IMG}" ]; then
  echo "Output image not found or empty: ${OUT_IMG}" >&2
  exit 1
fi
sha256_file="${OUT_IMG}.sha256"
sha256sum "${OUT_IMG}" > "${sha256_file}"
echo "[sugarkube] Image written to ${OUT_IMG}"
echo "[sugarkube] SHA256 checksum stored in ${sha256_file}"

BUILD_LOG_SEARCH_ROOT="${PI_GEN_DIR}/work/${IMG_NAME}"
BUILD_LOG_SOURCE="${BUILD_LOG_SEARCH_ROOT}/build.log"
append_pi_gen_log() {
  local source_path="$1"
  local header_suffix="$2"
  if [ ! -f "${source_path}" ]; then
    return 1
  fi

  local header="[sugarkube] --- pi-gen build.log ---"
  if [ -n "${header_suffix}" ]; then
    header="${header} (${header_suffix})"
  fi

  local decoder=(cat)
  local compression="plain"
  case "${source_path}" in
    *.xz)
      decoder=(xz -dc)
      compression="xz"
      ;;
    *.gz)
      decoder=(gzip -dc)
      compression="gz"
      ;;
  esac

  if ! {
    printf '\n%s\n' "${header}"
    "${decoder[@]}" "${source_path}"
  } >>"${BUILD_LOG}"; then
    echo "[sugarkube] Failed to append ${compression} log from ${source_path}" >&2
    return 1
  fi

  echo "[sugarkube] Build log appended from ${source_path} (${compression})"
}

if ! append_pi_gen_log "${BUILD_LOG_SOURCE}" ""; then
  if ! append_pi_gen_log "${BUILD_LOG_SOURCE}.xz" "${BUILD_LOG_SOURCE}.xz"; then
    if ! append_pi_gen_log "${BUILD_LOG_SOURCE}.gz" "${BUILD_LOG_SOURCE}.gz"; then
      nested_logs=()
      if [ -d "${BUILD_LOG_SEARCH_ROOT}" ]; then
        while IFS= read -r -d '' candidate; do
          nested_logs+=("${candidate}")
        done < <(find "${BUILD_LOG_SEARCH_ROOT}" -mindepth 2 -maxdepth 6 \
          -type f \( -name 'build.log' -o -name 'build.log.xz' -o -name 'build.log.gz' \) -print0 | sort -z)
      fi

      if [ "${#nested_logs[@]}" -gt 0 ]; then
        for candidate in "${nested_logs[@]}"; do
          append_pi_gen_log "${candidate}" "${candidate}" || true
        done
      else
        echo "[sugarkube] Build log not found under ${BUILD_LOG_SEARCH_ROOT}" >&2
      fi
    fi
  fi
fi

recover_just_log_line() {
  if grep -Fq '[sugarkube] just command verified' "${BUILD_LOG}"; then
    return 0
  fi

  if [ ! -d "${BUILD_LOG_SEARCH_ROOT}" ]; then
    echo "[sugarkube] Warning: just verification search root missing: ${BUILD_LOG_SEARCH_ROOT}" >&2
    return 1
  fi

  echo "[sugarkube] Recovering just verification log entries from ${BUILD_LOG_SEARCH_ROOT}" >&2

  local found=0
  local scanned=0
  local candidates=()
  while IFS= read -r -d '' candidate; do
    candidates+=("${candidate}")
  done < <(find "${BUILD_LOG_SEARCH_ROOT}" -mindepth 1 \
    -type f \( -name '*.log' -o -name '*.log.xz' -o -name '*.log.gz' -o -name '*.txt' \) -print0 | sort -z)

  for candidate in "${candidates[@]}"; do
    scanned=$((scanned + 1))
    local compression="plain"
    local decoder=(cat)
    case "${candidate}" in
      *.xz)
        compression="xz"
        decoder=(xz -dc)
        ;;
      *.gz)
        compression="gz"
        decoder=(gzip -dc)
        ;;
    esac

    if [[ "${compression}" == "plain" ]]; then
      if grep -Fq '[sugarkube] just command verified' "${candidate}"; then
        {
          printf '\n[sugarkube] --- stage log appended (%s) ---\n' "${candidate}"
          cat "${candidate}"
        } >>"${BUILD_LOG}"
        echo "[sugarkube] Recovered just verification log from ${candidate} (${compression})"
        found=1
        break
      fi
    else
      if "${decoder[@]}" "${candidate}" 2>/dev/null | grep -Fq '[sugarkube] just command verified'; then
        {
          printf '\n[sugarkube] --- stage log appended (%s) ---\n' "${candidate}"
          "${decoder[@]}" "${candidate}" 2>/dev/null
        } >>"${BUILD_LOG}"
        echo "[sugarkube] Recovered just verification log from ${candidate} (${compression})"
        found=1
        break
      fi
    fi

    echo "[sugarkube] Debug: just verification not found in ${candidate} (${compression})" >&2
  done

  if [ "${found}" -eq 0 ]; then
    echo "[sugarkube] Warning: just verification log line not found under ${BUILD_LOG_SEARCH_ROOT} (scanned ${scanned} candidates)" >&2
    return 1
  fi
}

recover_just_log_line || true

REPO_DEPLOY_DIR="${REPO_ROOT}/deploy"
REPO_DEPLOY_LOG="${REPO_DEPLOY_DIR}/${IMG_NAME}.build.log"
mkdir -p "${REPO_DEPLOY_DIR}"
if [ "${REPO_DEPLOY_LOG}" != "${BUILD_LOG}" ]; then
  cp "${BUILD_LOG}" "${REPO_DEPLOY_LOG}"
fi

REPO_DEPLOY_IMAGE="${REPO_DEPLOY_DIR}/${IMG_NAME}.img.xz"
if [ "${REPO_DEPLOY_IMAGE}" != "${OUT_IMG}" ]; then
  cp "${OUT_IMG}" "${REPO_DEPLOY_IMAGE}"
fi

REPO_DEPLOY_SHA256="${REPO_DEPLOY_IMAGE}.sha256"
if [ "${REPO_DEPLOY_SHA256}" != "${sha256_file}" ]; then
  cp "${sha256_file}" "${REPO_DEPLOY_SHA256}"
fi

echo "[sugarkube] Build log available at ${REPO_DEPLOY_LOG}"

METADATA_PATH="${OUT_IMG}.metadata.json"
STAGE_SUMMARY_PATH="${OUT_IMG}.stage-summary.json"
metadata_args=(
  --output "${METADATA_PATH}"
  --image "${OUT_IMG}"
  --checksum "${sha256_file}"
  --pi-gen-branch "${PI_GEN_BRANCH}"
  --pi-gen-url "${PI_GEN_URL}"
  --pi-gen-commit "${PI_GEN_COMMIT}"
  --pi-gen-stages "${PI_GEN_STAGES}"
  --repo-commit "${REPO_COMMIT}"
  --repo-ref "${REPO_REF}"
  --build-start "${BUILD_STARTED_AT}"
  --build-end "${BUILD_COMPLETED_AT}"
  --duration-seconds "${BUILD_DURATION_SECONDS}"
  --runner-os "${RUNNER_OS_VALUE}"
  --runner-arch "${RUNNER_ARCH_VALUE}"
  --option "arm64=${ARM64}"
  --option "armhf=${ARMHF}"
  --option "clone_sugarkube=${CLONE_SUGARKUBE}"
  --option "clone_token_place=${CLONE_TOKEN_PLACE}"
  --option "clone_dspace=${CLONE_DSPACE}"
  --option "token_place_branch=${TOKEN_PLACE_BRANCH}"
  --option "dspace_branch=${DSPACE_BRANCH}"
)
if [ -n "${EXTRA_REPOS}" ]; then
  metadata_args+=(--option "extra_repos=${EXTRA_REPOS}")
fi
if [ -n "${PI_GEN_SOURCE_DIR}" ]; then
  metadata_args+=(--option "pi_gen_source_dir=${PI_GEN_SOURCE_DIR}")
fi
metadata_args+=(--build-log "${BUILD_LOG}")
metadata_args+=(--stage-summary "${STAGE_SUMMARY_PATH}")

python3 "${REPO_ROOT}/scripts/create_build_metadata.py" "${metadata_args[@]}"
echo "[sugarkube] Build metadata captured at ${METADATA_PATH}"
if [ -s "${STAGE_SUMMARY_PATH}" ]; then
  echo "[sugarkube] Stage summary captured at ${STAGE_SUMMARY_PATH}"
elif [ -e "${STAGE_SUMMARY_PATH}" ]; then
  echo "[sugarkube] Stage summary written to ${STAGE_SUMMARY_PATH} (no stage data)"
fi

REPO_DEPLOY_METADATA="${REPO_DEPLOY_DIR}/$(basename "${METADATA_PATH}")"
if [ "${REPO_DEPLOY_METADATA}" != "${METADATA_PATH}" ] && [ -f "${METADATA_PATH}" ]; then
  cp "${METADATA_PATH}" "${REPO_DEPLOY_METADATA}"
fi

REPO_DEPLOY_STAGE_SUMMARY="${REPO_DEPLOY_DIR}/$(basename "${STAGE_SUMMARY_PATH}")"
if [ "${REPO_DEPLOY_STAGE_SUMMARY}" != "${STAGE_SUMMARY_PATH}" ] && [ -f "${STAGE_SUMMARY_PATH}" ]; then
  cp "${STAGE_SUMMARY_PATH}" "${REPO_DEPLOY_STAGE_SUMMARY}"
fi
