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

verify_checksum_relocation() {
  local artifact="$1"
  local checksum="${artifact}.sha256"
  local dest
  dest="$(mktemp -d "${tmp}/verify.XXXXXX")"
  local artifact_name
  artifact_name="$(basename "${artifact}")"
  local checksum_name
  checksum_name="$(basename "${checksum}")"
  mv "${artifact}" "${dest}/${artifact_name}"
  mv "${checksum}" "${dest}/${checksum_name}"
  (
    cd "${dest}" && sha256sum -c "${checksum_name}" >/dev/null
  )
  mv "${dest}/${artifact_name}" "${artifact}"
  mv "${dest}/${checksum_name}" "${checksum}"
  rmdir "${dest}"
}

# Case 1: nested pre-compressed .img.xz
mkdir -p "${tmp}/deploy/nested"
echo "hello-from-xz" > "${tmp}/deploy/nested/foo.img"
xz -c ${XZ_OPT} "${tmp}/deploy/nested/foo.img" > "${tmp}/deploy/nested/foo.img.xz"
rm -f "${tmp}/deploy/nested/foo.img"
bash "${SCRIPT}" "${tmp}/deploy" "${tmp}/out1.img.xz"
test -s "${tmp}/out1.img.xz"
test -s "${tmp}/out1.img.xz.sha256"
( cd "${tmp}" && sha256sum -c "$(basename "${tmp}/out1.img.xz").sha256" >/dev/null )
verify_checksum_relocation "${tmp}/out1.img.xz"

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
( cd "${tmp}" && sha256sum -c "$(basename "${tmp}/out2.img.xz").sha256" >/dev/null )
verify_checksum_relocation "${tmp}/out2.img.xz"

# Reset deploy between cases
rm -rf "${tmp}/deploy"

# Case 3: raw .img
mkdir -p "${tmp}/deploy/rawcase"
dd if=/dev/zero of="${tmp}/deploy/rawcase/baz.img" bs=1 count=16 status=none
bash "${SCRIPT}" "${tmp}/deploy" "${tmp}/out3.img.xz"
test -s "${tmp}/out3.img.xz"
test -s "${tmp}/out3.img.xz.sha256"
( cd "${tmp}" && sha256sum -c "$(basename "${tmp}/out3.img.xz").sha256" >/dev/null )
verify_checksum_relocation "${tmp}/out3.img.xz"

# Reset deploy between cases
rm -rf "${tmp}/deploy"

# Case 4: gz-compressed .img
mkdir -p "${tmp}/deploy/gzcase"
echo "hi-from-gz" > "${tmp}/deploy/gzcase/qux.img"
gzip -c "${tmp}/deploy/gzcase/qux.img" > "${tmp}/deploy/gzcase/qux.img.gz"
rm -f "${tmp}/deploy/gzcase/qux.img"
bash "${SCRIPT}" "${tmp}/deploy" "${tmp}/out4.img.xz"
test -s "${tmp}/out4.img.xz"
test -s "${tmp}/out4.img.xz.sha256"
( cd "${tmp}" && sha256sum -c "$(basename "${tmp}/out4.img.xz").sha256" >/dev/null )
verify_checksum_relocation "${tmp}/out4.img.xz"

# Reset deploy between cases
rm -rf "${tmp}/deploy"

# Case 5: already-normalized artifact at output path
echo "pre-existing" > "${tmp}/foo.img"
xz -c ${XZ_OPT} "${tmp}/foo.img" > "${tmp}/foo.img.xz"
rm -f "${tmp}/foo.img"
bash "${SCRIPT}" "${tmp}" "${tmp}/foo.img.xz"
test -s "${tmp}/foo.img.xz"
test -s "${tmp}/foo.img.xz.sha256"
( cd "${tmp}" && sha256sum -c "$(basename "${tmp}/foo.img.xz").sha256" >/dev/null )
verify_checksum_relocation "${tmp}/foo.img.xz"

# Case 6: pi-image workflow log verification handles nested logs
rm -rf "${tmp}/deploy"
mkdir -p "${tmp}/deploy/nested/logs"
cat >"${tmp}/deploy/nested/logs/sugarkube.build.log" <<'EOF'
[sugarkube] just command verified at /usr/bin/just
[sugarkube] just version: stub
EOF

# Sanity check: the old maxdepth=2 search should fail so we know the regression is covered
if ( cd "${tmp}" && bash -euo pipefail -c '
  mapfile -t logs < <(find deploy -maxdepth 2 -name '\''*.build.log'\'' -print | sort)
  [ "${#logs[@]}" -gt 0 ] && exit 0
  exit 1
' ); then
  echo "maxdepth=2 unexpectedly found nested logs" >&2
  exit 1
fi

verify_snippet="${tmp}/verify_just.sh"
cat >"${verify_snippet}" <<'EOSH'
#!/usr/bin/env bash
set -euo pipefail

mapfile -t logs < <(find deploy -maxdepth 3 -name '*.build.log' -print | sort)
if [ "${#logs[@]}" -eq 0 ]; then
  echo "no build logs discovered" >&2
  exit 1
fi

found=0
for log in "${logs[@]}"; do
  if grep -FH 'just command verified' "${log}" >/dev/null; then
    found=1
    grep -FH '[sugarkube] just version' "${log}" >/dev/null || true
  fi
done

if [ "${found}" -eq 0 ]; then
  echo "missing just verification log entry" >&2
  exit 1
fi
EOSH
chmod +x "${verify_snippet}"
( cd "${tmp}" && bash "${verify_snippet}" )

echo "All artifact detection tests passed."
