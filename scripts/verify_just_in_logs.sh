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

DEPLOY_REALPATH=$(realpath "${DEPLOY_DIR}")
echo "Scanning logs under: ${DEPLOY_REALPATH}"

logs=()
while IFS= read -r -d '' log; do
  logs+=("${log}")
done < <(
  find "${DEPLOY_DIR}" -maxdepth 8 -type f \
    \( -name '*.build.log' -o -name 'build.log' -o -path '*/log/*.log' \) -print0 | sort -z
)

if [ "${#logs[@]}" -eq 0 ]; then
  echo "No build logs found under ${DEPLOY_REALPATH}" >&2
  exit 2
fi

echo "Found ${#logs[@]} log file(s):"
for log in "${logs[@]}"; do
  log_realpath=$(realpath "${log}")
  log_size=$(stat -c '%s' "${log}")
  printf '  - %s (%s bytes)\n' "${log_realpath}" "${log_size}"
done

marker_found=0
marker_log=""
for log in "${logs[@]}"; do
  if grep -Fqs 'just command verified' "${log}"; then
    marker_found=1
    marker_log=$(realpath "${log}")
    break
  fi
done

if [ "${marker_found}" -eq 1 ]; then
  echo "Marker found in: ${marker_log}"
  version_lines=$(grep -Fh '[sugarkube] just version' "${logs[@]}" || true)
  if [ -n "${version_lines}" ]; then
    echo "[sugarkube] just version lines:"
    printf '%s\n' "${version_lines}" | sort -u
  else
    echo "No [sugarkube] just version lines present in logs."
  fi
  exit 0
fi

echo "just command verified marker missing from logs" >&2
echo "--- grep just summary ---" >&2
for log in "${logs[@]}"; do
  log_realpath=$(realpath "${log}")
  echo "# ${log_realpath}" >&2
  if ! grep -Fn 'just' "${log}" >&2; then
    echo "(no matches)" >&2
  fi
  echo >&2
done
exit 1
