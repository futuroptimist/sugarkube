#!/usr/bin/env bash
# Inspect both aggregate and per-stage pi-gen logs for the "just" verification marker.
# pi-gen no longer guarantees the stage output is copied into deploy/*.build.log (see PR #1247),
# so we search both the root build log and nested stage logs for "just command verified".
set -euo pipefail

DEPLOY_DIR=${1:-deploy}
if [ ! -d "${DEPLOY_DIR}" ]; then
  echo "Deploy directory not found: ${DEPLOY_DIR}" >&2
  exit 2
fi

mapfile -d '' -t logs < <(
  find "${DEPLOY_DIR}" -maxdepth 8 -type f \
    \( -name '*.build.log' -o -name 'build.log' -o -path '*/log/*.log' \) \
    -print0 | sort -z
)

if [ "${#logs[@]}" -eq 0 ]; then
  echo "No build logs found under $(realpath "${DEPLOY_DIR}")" >&2
  exit 3
fi

for log in "${logs[@]}"; do
  if grep -Fqs 'just command verified' "${log}"; then
    echo "just command verified marker found in $(realpath "${log}")"
    version_lines=$(grep -Fh '[sugarkube] just version' "${logs[@]}" || true)
    if [ -n "${version_lines}" ]; then
      printf '%s\n' "${version_lines}" | sort -u
    fi
    exit 0
  fi
done

echo "Missing 'just command verified' marker in logs under $(realpath "${DEPLOY_DIR}")" >&2
exit 1
