#!/usr/bin/env bash
# Ensure pi-image artifacts created by root-owned builds are writable by the caller.
set -euo pipefail

shopt -s nullglob

TARGET_UID="${TARGET_UID:-${SUDO_UID:-}}"
TARGET_GID="${TARGET_GID:-${SUDO_GID:-}}"

if [ -z "${TARGET_UID}" ] || [ -z "${TARGET_GID}" ]; then
  TARGET_UID="$(id -u)"
  TARGET_GID="$(id -g)"
fi

if [ -z "${TARGET_UID}" ] || [ -z "${TARGET_GID}" ]; then
  echo "ERROR: unable to determine target UID/GID" >&2
  exit 1
fi

declare -a paths=()

if [ -d deploy ]; then
  paths+=("deploy")
fi

while IFS= read -r -d '' file; do
  # Strip leading ./ for nicer logs while keeping relative paths.
  if [[ "${file}" == ./* ]]; then
    paths+=("${file:2}")
  else
    paths+=("${file}")
  fi
done < <(find . -maxdepth 1 -type f -name 'sugarkube*.img.xz*' -print0)

if [ "${#paths[@]}" -eq 0 ]; then
  echo "No pi-image artifacts found; nothing to fix."
  exit 0
fi

printf 'Fixing ownership of:%s\n' "${paths[*]/#/ }"

if ! chown -R "${TARGET_UID}:${TARGET_GID}" "${paths[@]}" 2>/tmp/fix_pi_image_permissions.err; then
  cat /tmp/fix_pi_image_permissions.err >&2
  rm -f /tmp/fix_pi_image_permissions.err
  echo "ERROR: failed to change ownership; try running with sudo" >&2
  exit 1
fi
rm -f /tmp/fix_pi_image_permissions.err

printf 'Updated ownership to %s:%s\n' "${TARGET_UID}" "${TARGET_GID}"
