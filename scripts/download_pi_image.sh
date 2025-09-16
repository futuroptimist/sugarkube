#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC2317
cleanup() {
  if [[ -n "${TMP_ASSET:-}" && -f "$TMP_ASSET" ]]; then
    rm -f "$TMP_ASSET"
  fi
  if [[ -n "${TMP_SHA:-}" && -f "$TMP_SHA" ]]; then
    rm -f "$TMP_SHA"
  fi
}

trap cleanup EXIT

log() {
  printf 'sugarkube: %s\n' "$*" >&2
}

die() {
  log "$*"
  exit 1
}

require() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "$1 is required"
  fi
}

usage() {
  cat <<'EOF'
Usage: download_pi_image.sh [options]

Fetch the latest published sugarkube image from GitHub Releases, resume partial
downloads, and verify the checksum.

Options:
  -o, --output PATH     Path for the compressed image (default: $HOME/sugarkube/images/sugarkube.img.xz)
  -r, --release TAG     Release tag to download (default: latest release)
      --repo OWNER/REPO Repository to query (default: futuroptimist/sugarkube)
      --asset NAME      Image asset name (default: sugarkube.img.xz)
      --checksum NAME   Checksum asset name (default: <asset>.sha256)
      --skip-verify     Skip checksum verification
  -f, --force           Re-download even if an existing verified file is present
  -h, --help            Show this help message
EOF
}

DEFAULT_REPO=${SUGARKUBE_GH_REPO:-futuroptimist/sugarkube}
DEFAULT_ASSET="sugarkube.img.xz"
DEFAULT_DIR=${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}

OUTPUT=""
RELEASE_TAG="latest"
REPO="$DEFAULT_REPO"
ASSET_NAME="$DEFAULT_ASSET"
CHECKSUM_NAME=""
SKIP_VERIFY=0
FORCE_DOWNLOAD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--output)
      OUTPUT="$2"
      shift 2
      ;;
    -r|--release)
      RELEASE_TAG="$2"
      shift 2
      ;;
    --repo)
      REPO="$2"
      shift 2
      ;;
    --asset)
      ASSET_NAME="$2"
      shift 2
      ;;
    --checksum)
      CHECKSUM_NAME="$2"
      shift 2
      ;;
    --skip-verify)
      SKIP_VERIFY=1
      shift
      ;;
    -f|--force)
      FORCE_DOWNLOAD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "Unknown option: $1"
      ;;
    *)
      if [[ -z "$OUTPUT" ]]; then
        OUTPUT="$1"
      else
        die "Unexpected argument: $1"
      fi
      shift
      ;;
  esac
done

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="$DEFAULT_DIR/$ASSET_NAME"
fi

if [[ -z "$CHECKSUM_NAME" ]]; then
  CHECKSUM_NAME="$ASSET_NAME.sha256"
fi

require gh
require curl
require sha256sum
require python3

mkdir -p "$(dirname "$OUTPUT")"

if [[ "$RELEASE_TAG" == "latest" ]]; then
  release_json=$(gh api "repos/$REPO/releases/latest")
else
  release_json=$(gh api "repos/$REPO/releases/tags/$RELEASE_TAG")
fi

if [[ -z "$release_json" ]]; then
  die "no release metadata found for $REPO"
fi

asset_url=$(python3 - "$ASSET_NAME" "$release_json" <<'PY'
import json
import sys

asset_name = sys.argv[1]
release = json.loads(sys.argv[2])

for asset in release.get("assets", []):
    if asset.get("name") == asset_name:
        print(asset.get("browser_download_url", ""))
        sys.exit(0)

sys.exit(1)
PY
) || true

if [[ -z "$asset_url" ]]; then
  die "asset $ASSET_NAME not found in release"
fi

checksum_url=$(python3 - "$CHECKSUM_NAME" "$release_json" <<'PY'
import json
import sys

asset_name = sys.argv[1]
release = json.loads(sys.argv[2])

for asset in release.get("assets", []):
    if asset.get("name") == asset_name:
        print(asset.get("browser_download_url", ""))
        sys.exit(0)

sys.exit(1)
PY
) || true

dest_sha="${OUTPUT}.sha256"

if auth_header_value=$(gh auth token 2>/dev/null); then
  AUTH_HEADER=("-H" "Authorization: token $auth_header_value")
else
  AUTH_HEADER=()
fi

download() {
  local url="$1"
  local dest="$2"
  TMP_ASSET=$(mktemp)
  log "Downloading $(basename "$dest")"
  if ! curl --fail --location --continue-at - --progress-bar \
      --retry 5 --retry-delay 2 --retry-max-time 120 \
      "${AUTH_HEADER[@]}" \
      -H "Accept: application/octet-stream" \
      --output "$TMP_ASSET" \
      "$url"; then
    rm -f "$TMP_ASSET"
    unset TMP_ASSET
    die "failed to download $(basename "$dest")"
  fi
  mv "$TMP_ASSET" "$dest"
  unset TMP_ASSET
}

normalize_checksum() {
  if [[ ! -f "$dest_sha" ]]; then
    return
  fi
  python3 - "$dest_sha" "$(basename "$OUTPUT")" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
target = sys.argv[2]

raw_lines = path.read_text().splitlines()

for raw_line in raw_lines:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    parts = stripped.split(maxsplit=1)
    digest = parts[0]
    remainder = parts[1] if len(parts) > 1 else ""
    candidate = remainder.strip().lstrip("*")
    if candidate in {target, f"./{target}"}:
        path.write_text(f"{digest}  {target}\n")
        break
    candidate_name = pathlib.Path(candidate).name if candidate else ""
    if candidate_name == target:
        path.write_text(f"{digest}  {target}\n")
        break
else:
    digests = [
        line.strip().split()[0]
        for line in raw_lines
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(digests) == 1:
        path.write_text(f"{digests[0]}  {target}\n")
    else:
        print(f"no checksum entry matched {target}", file=sys.stderr)
        sys.exit(1)
PY
}

download_checksum() {
  if [[ -z "$checksum_url" ]]; then
    log "no checksum asset available"
    return 1
  fi
  TMP_SHA=$(mktemp)
  log "Downloading checksum $(basename "$dest_sha")"
  if ! curl --fail --location --continue-at - --progress-bar \
      --retry 5 --retry-delay 2 --retry-max-time 120 \
      "${AUTH_HEADER[@]}" \
      -H "Accept: application/octet-stream" \
      --output "$TMP_SHA" \
      "$checksum_url"; then
    rm -f "$TMP_SHA"
    unset TMP_SHA
    die "failed to download checksum"
  fi
  mv "$TMP_SHA" "$dest_sha"
  unset TMP_SHA
  normalize_checksum
}

verify_checksum() {
  local allow_missing=${1:-0}
  if [[ $SKIP_VERIFY -eq 1 ]]; then
    return 0
  fi
  if [[ ! -f "$dest_sha" ]]; then
    log "Skipping verification (missing checksum asset)"
    if [[ $allow_missing -eq 1 ]]; then
      return 0
    fi
    return 1
  fi
  (cd "$(dirname "$OUTPUT")" && sha256sum --check "$(basename "$dest_sha")")
}

if [[ $SKIP_VERIFY -eq 0 ]]; then
  download_checksum || true
fi

if [[ -f "$OUTPUT" && $FORCE_DOWNLOAD -eq 0 ]]; then
  if verify_checksum 0; then
    log "Existing image verified, skipping download"
    exit 0
  else
    log "Existing image failed verification; re-downloading"
  fi
fi

download "$asset_url" "$OUTPUT"

if [[ $SKIP_VERIFY -eq 0 ]]; then
  download_checksum || true
  if ! verify_checksum 1; then
    die "checksum verification failed"
  fi
fi

ls -lh "$OUTPUT" "${dest_sha}" 2>/dev/null || ls -lh "$OUTPUT"
log "Image saved to $OUTPUT"
