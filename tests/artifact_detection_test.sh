#!/usr/bin/env bash
# Minimal, fast tests that validate artifact discovery and normalization logic.
set -euo pipefail

ROOT="$(pwd)"
SCRIPT="${ROOT}/scripts/collect_pi_image.sh"

if [ ! -f "${SCRIPT}" ]; then
  echo "collect_pi_image.sh missing"
  exit 1
fi

export XZ_OPT="-T0 -0"  # speed up compression during tests

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

# Case 1: nested pre-compressed .img.xz
mkdir -p "${tmp}/deploy/nested"
echo "hello-from-xz" > "${tmp}/deploy/nested/foo.img"
xz -c ${XZ_OPT} "${tmp}/deploy/nested/foo.img" > "${tmp}/deploy/nested/foo.img.xz"
rm -f "${tmp}/deploy/nested/foo.img"
bash "${SCRIPT}" "${tmp}/deploy" "${tmp}/out1.img.xz"
test -s "${tmp}/out1.img.xz"
test -s "${tmp}/out1.img.xz.sha256"

# Reset deploy between cases
rm -rf "${tmp}/deploy"

# Case 2: zip containing a .img (use bsdtar to avoid requiring 'zip')
mkdir -p "${tmp}/deploy/zipcase"
echo "hi-from-zip" > "${tmp}/deploy/zipcase/bar.img"
# bsdtar auto-detects format from extension with -a
bsdtar -a -cf "${tmp}/deploy/zipcase/bar.zip" -C "${tmp}/deploy/zipcase" bar.img
rm -f "${tmp}/deploy/zipcase/bar.img"
bash "${SCRIPT}" "${tmp}/deploy" "${tmp}/out2.img.xz"
test -s "${tmp}/out2.img.xz"
test -s "${tmp}/out2.img.xz.sha256"

# Reset deploy between cases
rm -rf "${tmp}/deploy"

# Case 3: raw .img
mkdir -p "${tmp}/deploy/rawcase"
dd if=/dev/zero of="${tmp}/deploy/rawcase/baz.img" bs=1 count=16 status=none
bash "${SCRIPT}" "${tmp}/deploy" "${tmp}/out3.img.xz"
test -s "${tmp}/out3.img.xz"
test -s "${tmp}/out3.img.xz.sha256"

# Case 4: already-normalized artifact at output path
echo "pre-existing" > "${tmp}/foo.img"
xz -c ${XZ_OPT} "${tmp}/foo.img" > "${tmp}/foo.img.xz"
rm -f "${tmp}/foo.img"
bash "${SCRIPT}" "${tmp}" "${tmp}/foo.img.xz"
test -s "${tmp}/foo.img.xz"
test -s "${tmp}/foo.img.xz.sha256"

echo "All artifact detection tests passed."
