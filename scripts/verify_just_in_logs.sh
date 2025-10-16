#!/usr/bin/env bash
# Inspect both aggregate build logs and per-stage logs for the just verification marker.
# pi-gen stopped always copying the marker into build.log (see PR #1247), so we scan both.
set -euo pipefail

DEPLOY_DIR_INPUT="${1:-deploy}"
HAS_REALPATH=0
if command -v realpath >/dev/null 2>&1; then
  HAS_REALPATH=1
fi

resolve_path() {
  if [ "${HAS_REALPATH}" -eq 1 ]; then
    realpath -m -- "$1"
  else
    python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"
  fi
}

if [ ! -d "${DEPLOY_DIR_INPUT}" ]; then
  printf 'Deploy directory not found: %s\n' "${DEPLOY_DIR_INPUT}" >&2
  printf 'No log files to inspect.\n' >&2
  exit 2
fi

DEPLOY_DIR="$(resolve_path "${DEPLOY_DIR_INPUT}")"

printf 'Scanning log files under %s\n' "${DEPLOY_DIR}"

mapfile -d '' -t LOG_FILES < <(
  find "${DEPLOY_DIR}" -maxdepth 8 -type f \
    \( -name '*.build.log' -o -name 'build.log' -o -path '*/log/*.log' \) -print0
)

if [ "${#LOG_FILES[@]}" -eq 0 ]; then
  printf 'No matching log files found in %s\n' "${DEPLOY_DIR}" >&2
  exit 2
fi

printf 'Found %d log file(s):\n' "${#LOG_FILES[@]}"
for log in "${LOG_FILES[@]}"; do
  log_path="$(resolve_path "${log}")"
  if size=$(stat -c '%s' "${log}" 2>/dev/null); then
    :
  else
    size=$(wc -c <"${log}")
  fi
  printf '  • %s (%s bytes)\n' "${log_path}" "${size}"
done

marker_found=0
marker_log=""
for log in "${LOG_FILES[@]}"; do
  if grep -Fq 'just command verified' "${log}"; then
    marker_found=1
    marker_log="${log}"
    break
  fi
done

if [ "${marker_found}" -eq 1 ]; then
  marker_log_path="$(resolve_path "${marker_log}")"
  printf 'just verification marker found in %s\n' "${marker_log_path}"
  grep -hF '[sugarkube] just version' -- "${LOG_FILES[@]}" || true
  exit 0
fi

printf 'just verification marker missing.\n' >&2
printf 'Checked logs:\n' >&2
for log in "${LOG_FILES[@]}"; do
  log_path="$(resolve_path "${log}")"
  printf '  %s\n' "${log_path}" >&2
done
printf '%s\n' '--- grep just summary ---' >&2
if ! grep -HnF 'just' -- "${LOG_FILES[@]}" >&2; then
  printf 'No occurrences of "just" found in logs.\n' >&2
fi
exit 1
