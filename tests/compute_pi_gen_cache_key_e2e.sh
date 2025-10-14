#!/usr/bin/env bash
# Validate scripts/compute_pi_gen_cache_key.sh against success and failure scenarios.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/compute_pi_gen_cache_key.sh"

if [ ! -x "${SCRIPT}" ]; then
  echo "compute_pi_gen_cache_key.sh missing or not executable" >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmpdir}"
}
trap cleanup EXIT

remote_repo="${tmpdir}/pi-gen-remote.git"
work_repo="${tmpdir}/work"

git init --bare "${remote_repo}" >/dev/null 2>&1

git init "${work_repo}" >/dev/null 2>&1
(
  cd "${work_repo}"
  git config user.name "Test User"
  git config user.email "test@example.com"
  printf 'cache-key-e2e' > README.md
  git add README.md
  git commit -m "initial" >/dev/null 2>&1
  git branch -M main
  git push "${remote_repo}" main:bookworm >/dev/null 2>&1
)

commit_ref="$(git --git-dir="${remote_repo}" rev-parse bookworm)"
expected_month="$(date -u +'%Y-%m')"

runner_label="TestOS"
key_output="$(RUNNER_OS="${runner_label}" bash "${SCRIPT}" bookworm "${remote_repo}")"
expected_key="pigen-${runner_label}-bookworm-${commit_ref}-${expected_month}"
if [ "${key_output}" != "${expected_key}" ]; then
  printf 'unexpected cache key: got %s expected %s\n' "${key_output}" "${expected_key}" >&2
  exit 1
fi

offline_output="$(RUNNER_OS="OfflineOS" bash "${SCRIPT}" bookworm "${tmpdir}/missing.git" 2>"${tmpdir}/stderr.log")"
if [[ "${offline_output}" != pigen-OfflineOS-bookworm-offline-${expected_month} ]]; then
  printf 'offline cache key mismatch: %s\n' "${offline_output}" >&2
  exit 1
fi

if ! grep -q "falling back to offline cache key" "${tmpdir}/stderr.log"; then
  echo "expected fallback warning not emitted" >&2
  exit 1
fi

echo "compute_pi_gen_cache_key e2e test passed"
