#!/usr/bin/env bash
#
# Harvest pi-gen logs for the "just command verified" marker.
# Newer pi-gen releases sometimes omit stage output from deploy/*/build.log.
# See PR #1247 for context—scan both aggregate and per-stage logs.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: verify_just_in_logs.sh [DEPLOY_DIR]

Search DEPLOY_DIR (default: deploy) for pi-gen logs containing the
"just command verified" marker. Returns 0 if found, 1 if missing, 2 if no logs.
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

deploy_dir=${1:-deploy}
if [[ -z ${deploy_dir} ]]; then
  echo "Deploy directory argument must not be empty" >&2
  exit 2
fi

if [[ ! -d ${deploy_dir} ]]; then
  echo "Deploy directory not found: ${deploy_dir}" >&2
  exit 2
fi

deploy_realpath=$(realpath "${deploy_dir}")

mapfile -d '' logs < <(
  find "${deploy_realpath}" -maxdepth 8 -type f \
    \( -name '*.build.log' -o -name 'build.log' -o -path '*/log/*.log' \) \
    -print0 | sort -z
)

if [[ ${#logs[@]} -eq 0 ]]; then
  echo "No log files under ${deploy_realpath} matching '*.build.log', 'build.log', or '*/log/*.log'" >&2
  exit 2
fi

echo "Inspecting logs under ${deploy_realpath}:"
for log in "${logs[@]}"; do
  size=$(du -h "${log}" | awk '{print $1}')
  printf '  • %s (%s)\n' "${log}" "${size}"
done

declare -i found=0
if grep -Fq 'just command verified' "${logs[@]}"; then
  found=1
fi

if (( found == 1 )); then
  echo "just marker located. Captured just version lines:"
  if ! grep -Fh '[sugarkube] just version' "${logs[@]}"; then
    echo "(no [sugarkube] just version lines found)"
  fi
  exit 0
fi

echo "'just command verified' marker missing across inspected logs." >&2
echo "Grep summary for 'just':" >&2
mapfile -t just_lines < <(grep -FHi -n 'just' "${logs[@]}" || true)
if (( ${#just_lines[@]} > 0 )); then
  limit=${#just_lines[@]}
  if (( limit > 20 )); then
    limit=20
  fi
  for ((i = 0; i < limit; i++)); do
    printf '%s\n' "${just_lines[i]}" >&2
  done
  if (( ${#just_lines[@]} > limit )); then
    echo "... (truncated)" >&2
  fi
else
  echo "No other 'just' references found." >&2
fi
exit 1
