#!/usr/bin/env bash
# Search pi-gen build logs for the just verification marker. pi-gen stopped copying the
# marker into the top-level build.log (see PR #1247), so inspect both aggregate and
# per-stage logs.
set -euo pipefail

readonly deploy_root="${1:-deploy}"

if ! deploy_realpath=$(realpath "${deploy_root}" 2>/dev/null); then
  echo "Deploy directory '${deploy_root}' not found" >&2
  exit 2
fi

if [ ! -d "${deploy_realpath}" ]; then
  echo "Deploy directory '${deploy_realpath}' not found" >&2
  exit 2
fi

mapfile -d '' -t logs < <(find "${deploy_realpath}" -maxdepth 8 -type f \
  \( -name '*.build.log' -o -name 'build.log' -o -path '*/log/*.log' \) -print0 | sort -z)

if [ "${#logs[@]}" -eq 0 ]; then
  echo "No build logs found under ${deploy_realpath}" >&2
  exit 2
fi

echo "Scanning $((${#logs[@]})) log(s) under ${deploy_realpath}" >&2
for log in "${logs[@]}"; do
  if [ -f "${log}" ]; then
    if ! size=$(stat -c '%s' "${log}" 2>/dev/null); then
      size=$(wc -c <"${log}")
    fi
    printf '  • %s (%s bytes)\n' "$(realpath "${log}")" "${size}" >&2
  else
    printf '  • %s (missing)\n' "${log}" >&2
  fi
done

found=0
for log in "${logs[@]}"; do
  if grep -Fq 'just command verified' "${log}"; then
    if [ "${found}" -eq 0 ]; then
      echo "just verification marker found:" >&2
    fi
    found=1
    printf '  %s\n' "$(realpath "${log}")"
    grep -F '[sugarkube] just version' "${log}" || true
  fi
done

if [ "${found}" -eq 1 ]; then
  exit 0
fi

echo "just verification marker missing under ${deploy_realpath}" >&2
echo "--- grep summary for 'just' ---" >&2
for log in "${logs[@]}"; do
  echo "# ${log}" >&2
  if ! grep -nF 'just' "${log}" >&2; then
    echo "(no occurrences)" >&2
  fi
  echo >&2
done

exit 1
