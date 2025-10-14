#!/usr/bin/env bash
# Normalize pi-gen output (wherever it lands under deploy/) into ./sugarkube.img.xz
# Usage: bash scripts/collect_pi_image.sh [DEPLOY_ROOT] [OUTPUT_PATH]
set -euo pipefail

tmpdirs=()
cleanup_tmpdirs() {
  for dir in "${tmpdirs[@]:-}"; do
    rm -rf "$dir"
  done
}
trap cleanup_tmpdirs EXIT

DEPLOY_ROOT="${1:-deploy}"
OUTPUT_PATH="${2:-sugarkube.img.xz}"
MAX_SCAN_DEPTH="${MAX_SCAN_DEPTH:-6}"

# Log what's in deploy for debuggability
echo "==> Scanning '${DEPLOY_ROOT}' for image artifacts"
if [ -d "${DEPLOY_ROOT}" ]; then
  find "${DEPLOY_ROOT}" -maxdepth "${MAX_SCAN_DEPTH}" -type f -printf '%p\t%k KB\n' | sort || true
else
  echo "ERROR: '${DEPLOY_ROOT}' does not exist" >&2
  exit 1
fi

# Helper: find first match by pattern preference
_find_first() {
  local pat="$1"
  # Prioritize shallower and lexicographically-stable paths
  find "${DEPLOY_ROOT}" -maxdepth "${MAX_SCAN_DEPTH}" -type f -name "${pat}" -printf '%d\t%p\n' \
    | sort -n | cut -f2 | head -n1
}

found=""
# Prefer pre-compressed images
found="$(_find_first '*.img.xz' || true)"
if [ -z "${found}" ]; then
  # Accept zip bundles containing a .img
  zipfile="$(_find_first '*.zip' || true)"
  if [ -n "${zipfile}" ]; then
    tmpdir="$(mktemp -d)"
    tmpdirs+=("$tmpdir")
    # Prefer bsdtar (libarchive) and fallback to unzip if unavailable
    if command -v bsdtar >/dev/null 2>&1; then
      bsdtar -xf "${zipfile}" -C "${tmpdir}"
    elif command -v unzip >/dev/null 2>&1; then
      unzip -q "${zipfile}" -d "${tmpdir}"
    else
      echo "ERROR: neither bsdtar nor unzip available to extract ${zipfile}" >&2
      exit 1
    fi
    img_in_zip="$(find "${tmpdir}" -type f -name '*.img' | head -n1 || true)"
    if [ -n "${img_in_zip}" ]; then
      found="${img_in_zip}"
    else
      echo "ERROR: Zip contained no .img: ${zipfile}" >&2
      exit 1
    fi
  fi
fi

if [ -z "${found}" ]; then
  # Accept gz-compressed .img
  gzfile="$(_find_first '*.img.gz' || true)"
  if [ -n "${gzfile}" ]; then
    tmpdir="$(mktemp -d)"
    tmpdirs+=("$tmpdir")
    gunzip -c "${gzfile}" > "${tmpdir}/image.img"
    found="${tmpdir}/image.img"
  fi
fi

if [ -z "${found}" ]; then
  # Finally, accept raw .img
  rawimg="$(_find_first '*.img' || true)"
  if [ -n "${rawimg}" ]; then
    found="${rawimg}"
  fi
fi

if [ -z "${found}" ]; then
  echo "ERROR: No image file found under '${DEPLOY_ROOT}' (looked for *.img.xz, *.zip, *.img.gz, *.img)" >&2
  exit 1
fi

echo "==> Found image source: ${found}"

# Normalize to .xz (keep original artifact in place for forensics)
mkdir -p "$(dirname "${OUTPUT_PATH}")"

# Use -ef to compare paths without relying on non-POSIX realpath
if [[ "${found}" == *.img.xz ]]; then
  if [ -e "${OUTPUT_PATH}" ] && [ "${found}" -ef "${OUTPUT_PATH}" ]; then
    echo "==> Source already at ${OUTPUT_PATH}, skipping copy"
  else
    cp -f "${found}" "${OUTPUT_PATH}"
  fi
else
  # Aim for deterministic-ish output:
  # - fix mtime of input so xz header doesn't vary
  # - respect SOURCE_DATE_EPOCH if set; else git commit time; else now
  SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct 2>/dev/null || date +%s)}"
  touch -d "@${SOURCE_DATE_EPOCH}" "${found}" || true

  # Compress; -e for better ratio, -T0 to use all cores on the runner
  : "${XZ_OPT:=-T0 -9e}"
  echo "==> Compressing to ${OUTPUT_PATH} (XZ_OPT='${XZ_OPT}')"
  xz -c ${XZ_OPT} "${found}" > "${OUTPUT_PATH}"
fi

# Write checksum next to artifact
# Remove any existing checksum file so read-only artifacts don't block new writes
checksum_path="${OUTPUT_PATH}.sha256"
rm -f "${checksum_path}"
artifact_dir="$(dirname "${OUTPUT_PATH}")"
artifact_name="$(basename "${OUTPUT_PATH}")"
(
  cd "${artifact_dir}" >/dev/null 2>&1 || {
    echo "ERROR: failed to enter artifact directory '${artifact_dir}'" >&2
    exit 1
  }
  sha256sum "${artifact_name}"
) > "${checksum_path}"

echo "==> Wrote:"
ls -lh "${OUTPUT_PATH}" "${checksum_path}"
