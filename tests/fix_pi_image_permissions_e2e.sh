#!/usr/bin/env bash
# Exercise scripts/fix_pi_image_permissions.sh against root-owned artifacts.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/fix_pi_image_permissions.sh"

if [ ! -x "${SCRIPT}" ]; then
  echo "fix_pi_image_permissions.sh missing or not executable" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmpdir}"
}
trap cleanup EXIT

workspace="${tmpdir}/workspace"
mkdir -p "${workspace}/deploy/nested"

# Create fake artifacts as the current user first.
printf 'artifact' > "${workspace}/sugarkube.img.xz"
printf 'sha256  sugarkube.img.xz' > "${workspace}/sugarkube.img.xz.sha256"
printf 'log' > "${workspace}/deploy/nested/example.build.log"

# Make the workspace root-owned to simulate the manual workflow.
sudo chown -R root:root "${workspace}"

# Run the fixer while cd'ing into the workspace so relative paths match CI usage.
(
  cd "${workspace}"
  sudo TARGET_UID="$(id -u)" TARGET_GID="$(id -g)" bash "${SCRIPT}"
)

expected_uid="$(id -u)"
expected_gid="$(id -g)"

check_owner() {
  local path="$1"
  local uid gid
  uid="$(stat -c '%u' "$path")"
  gid="$(stat -c '%g' "$path")"
  if [ "${uid}" != "${expected_uid}" ] || [ "${gid}" != "${expected_gid}" ]; then
    printf 'ownership mismatch for %s: got %s:%s expected %s:%s\n' \
      "$path" "$uid" "$gid" "$expected_uid" "$expected_gid" >&2
    exit 1
  fi
}

check_owner "${workspace}/deploy"
check_owner "${workspace}/deploy/nested/example.build.log"
check_owner "${workspace}/sugarkube.img.xz"
check_owner "${workspace}/sugarkube.img.xz.sha256"

echo "fix_pi_image_permissions e2e test passed"
