#!/usr/bin/env bash
# Compute a cache key for pi-gen Docker image downloads that tolerates
# temporary network failures. Outputs key/value pairs suitable for
# appending directly to GITHUB_OUTPUT.
set -euo pipefail

branch="${PI_GEN_BRANCH:-bookworm}"
remote="${PI_GEN_REMOTE:-https://github.com/RPi-Distro/pi-gen.git}"
runner_os="${RUNNER_OS:-linux}"
month="${PI_GEN_CACHE_MONTH:-$(date -u +'%Y-%m')}"
restore_prefix="pigen-${runner_os}-${branch}-"
ref=""
fallback="false"

if ref="$(git ls-remote "${remote}" "refs/heads/${branch}" | head -n1 | cut -f1)"; then
  ref="${ref%%$'\n'*}"
  if [ -z "${ref}" ]; then
    fallback="true"
    ref="fallback"
  fi
else
  fallback="true"
  ref="fallback"
fi

key="${restore_prefix}${ref}-${month}"

{
  echo "key=${key}"
  echo "restore_prefix=${restore_prefix}"
  echo "ref=${ref}"
  echo "fallback=${fallback}"
} | sed 's/\r$//'
