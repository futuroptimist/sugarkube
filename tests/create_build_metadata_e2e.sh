#!/usr/bin/env bash
# End-to-end smoke test for scripts/create_build_metadata.py.
# Creates a minimal fake pi-gen output and verifies metadata generation succeeds.
set -euo pipefail

TMPDIR_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_ROOT}"' EXIT

export PYTHONWARNINGS="error::DeprecationWarning"

RAW_IMAGE="${TMPDIR_ROOT}/image.raw"
printf 'sugarkube-metadata-smoke-test' > "${RAW_IMAGE}"

LOCAL_XZ_OPT="${XZ_OPT:--T0 -0}"
IMAGE_PATH="${TMPDIR_ROOT}/sugarkube.img.xz"
XZ_OPT="${LOCAL_XZ_OPT}" xz -c "${RAW_IMAGE}" > "${IMAGE_PATH}"
rm -f "${RAW_IMAGE}"

(
  cd "${TMPDIR_ROOT}"
  sha256sum "$(basename "${IMAGE_PATH}")" > "$(basename "${IMAGE_PATH}").sha256"
)
CHECKSUM_PATH="${IMAGE_PATH}.sha256"

BUILD_LOG="${TMPDIR_ROOT}/build.log"
cat <<'LOG' > "${BUILD_LOG}"
[00:00:00] Begin stage0
[00:00:05] End stage0
[00:00:05] Begin stage1
[00:01:05] End stage1
[00:01:06] Begin export-image
[00:01:36] End export-image
LOG

STAGE_SUMMARY="${TMPDIR_ROOT}/stage-summary.json"
METADATA_PATH="${TMPDIR_ROOT}/metadata.json"

python3 scripts/create_build_metadata.py \
  --output "${METADATA_PATH}" \
  --image "${IMAGE_PATH}" \
  --checksum "${CHECKSUM_PATH}" \
  --pi-gen-branch "bookworm" \
  --pi-gen-url "https://github.com/RPi-Distro/pi-gen.git" \
  --pi-gen-commit "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" \
  --pi-gen-stages "stage0 stage1 export-image" \
  --repo-commit "cafebabecafebabecafebabecafebabecafebabe" \
  --repo-ref "refs/heads/test" \
  --build-start "2024-01-01T00:00:00Z" \
  --build-end "2024-01-01T00:10:00Z" \
  --duration-seconds "600" \
  --runner-os "Linux" \
  --runner-arch "x86_64" \
  --option "arm64=1" \
  --option "clone_sugarkube=false" \
  --build-log "${BUILD_LOG}" \
  --stage-summary "${STAGE_SUMMARY}"

python3 - <<'PY' "${METADATA_PATH}" "${STAGE_SUMMARY}"
import json
import pathlib
import sys

metadata_path = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])

if not metadata_path.is_file():
    raise SystemExit(f"metadata missing: {metadata_path}")
if not summary_path.is_file():
    raise SystemExit(f"stage summary missing: {summary_path}")

metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
summary = json.loads(summary_path.read_text(encoding="utf-8"))

assert metadata["image"]["sha256"], "missing image sha256"
assert metadata["build"]["stage_durations"]["stage0"] == 5
assert metadata["build"]["stage_durations"]["stage1"] == 60
assert summary["stage_count"] == 3
assert summary["incomplete_stages"] == []
PY

echo "create_build_metadata smoke test passed"
