#!/usr/bin/env bash
# Compute the cache key for the pi-gen Docker image with a graceful fallback.
set -euo pipefail

BRANCH="${1:-bookworm}"
REMOTE="${2:-https://github.com/RPi-Distro/pi-gen.git}"
RUNNER_OS_NAME="${RUNNER_OS:-Linux}"

month="$(date -u +'%Y-%m')"
ref=""

if ref=$(git ls-remote "${REMOTE}" "refs/heads/${BRANCH}" 2>/dev/null | cut -f1); then
  if [ -z "${ref}" ]; then
    echo "warning: git ls-remote succeeded but returned no ref for ${REMOTE} ${BRANCH}" >&2
    ref="unknown"
  fi
else
  echo "warning: git ls-remote failed for ${REMOTE} ${BRANCH}; falling back to offline cache key" >&2
  ref="offline"
fi

printf 'pigen-%s-%s-%s-%s\n' "${RUNNER_OS_NAME}" "${BRANCH}" "${ref}" "${month}"
