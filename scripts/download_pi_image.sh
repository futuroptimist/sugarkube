#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Download the latest published sugarkube Pi image release.

Usage:
  download_pi_image.sh [OPTIONS] [OUTPUT]

Options:
  --tag <tag>        Download a specific release tag instead of the latest.
  --repo <owner/repo>
                     Override the GitHub repository (default: futuroptimist/sugarkube).
  --asset <name>     Override the image asset name (default: sugarkube.img.xz).
  --checksum <name>  Override the checksum asset name (default: <asset>.sha256).
  -h, --help         Show this message.

When OUTPUT is omitted, the image is saved to
  ${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}/sugarkube.img.xz
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  echo "sha256sum or shasum is required" >&2
  exit 1
fi

REPO_DEFAULT="futuroptimist/sugarkube"
TAG="latest"
REPO="${SUGARKUBE_REPO:-$REPO_DEFAULT}"
ASSET_NAME="${SUGARKUBE_IMAGE_ASSET:-sugarkube.img.xz}"
CHECKSUM_NAME=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      if [[ $# -lt 2 ]]; then
        echo "--tag requires an argument" >&2
        exit 1
      fi
      TAG="$2"
      shift 2
      ;;
    --repo)
      if [[ $# -lt 2 ]]; then
        echo "--repo requires an argument" >&2
        exit 1
      fi
      REPO="$2"
      shift 2
      ;;
    --asset)
      if [[ $# -lt 2 ]]; then
        echo "--asset requires an argument" >&2
        exit 1
      fi
      ASSET_NAME="$2"
      shift 2
      ;;
    --checksum)
      if [[ $# -lt 2 ]]; then
        echo "--checksum requires an argument" >&2
        exit 1
      fi
      CHECKSUM_NAME="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -* )
      echo "unknown option: $1" >&2
      usage
      exit 1
      ;;
    *)
      if [[ -n "$OUTPUT" ]]; then
        echo "unexpected argument: $1" >&2
        usage
        exit 1
      fi
      OUTPUT="$1"
      shift
      ;;
  esac
done

if [[ -z "$OUTPUT" ]]; then
  DEFAULT_DIR="${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}"
  OUTPUT="$DEFAULT_DIR/$ASSET_NAME"
fi

DEFAULT_DIRNAME=$(dirname "$OUTPUT")
mkdir -p "$DEFAULT_DIRNAME"

if [[ -z "$CHECKSUM_NAME" ]]; then
  CHECKSUM_NAME="$ASSET_NAME.sha256"
fi

CHECKSUM_OUTPUT="$OUTPUT.sha256"

cleanup_on_error() {
  local status=$?
  if [[ $status -ne 0 ]]; then
    echo "Download failed; leaving any partial files for inspection." >&2
  fi
  exit $status
}
trap cleanup_on_error EXIT

API_PATH="repos/$REPO/releases/latest"
if [[ "$TAG" != "latest" ]]; then
  API_PATH="repos/$REPO/releases/tags/$TAG"
fi

if ! release_json=$(gh api "$API_PATH" 2>/dev/null); then
  if [[ "$TAG" == "latest" ]]; then
    echo "no published releases found for $REPO" >&2
  else
    echo "release $TAG not found for $REPO" >&2
  fi
  exit 1
fi

export ASSET_NAME CHECKSUM_NAME RELEASE_JSON="$release_json"
mapfile -t parsed < <(
  python3 <<'PY'
import json
import os
import sys

data = json.loads(os.environ["RELEASE_JSON"])
asset_name = os.environ["ASSET_NAME"]
checksum_name = os.environ["CHECKSUM_NAME"]

def find(name):
    for asset in data.get("assets", []):
        if asset.get("name") == name:
            return asset.get("browser_download_url", "")
    return ""

img_url = find(asset_name)
sha_url = find(checksum_name)
if not img_url:
    sys.stderr.write(f"asset {asset_name} not found in release\n")
    sys.exit(1)
if not sha_url:
    sys.stderr.write(f"asset {checksum_name} not found in release\n")
    sys.exit(1)

print(data.get("tag_name", ""))
print(img_url)
print(sha_url)
PY
)

TAG_NAME="${parsed[0]:-}"
IMG_URL="${parsed[1]:-}"
SHA_URL="${parsed[2]:-}"

if [[ -z "$IMG_URL" ]]; then
  echo "image asset URL not found" >&2
  exit 1
fi
if [[ -z "$SHA_URL" ]]; then
  echo "checksum asset URL not found" >&2
  exit 1
fi

auth_header=()
if gh auth status >/dev/null 2>&1; then
  if token=$(gh auth token 2>/dev/null); then
    if [[ -n "$token" ]]; then
      auth_header=(-H "Authorization: token $token")
    fi
  fi
fi

download() {
  local url="$1"
  local dest="$2"
  local label="$3"

  echo "➡️  Downloading $label from ${TAG_NAME:-$TAG}"
  local args=(
    --fail
    --location
    --retry 3
    --retry-delay 2
    --continue-at -
    --progress-bar
  )
  if [[ ${#auth_header[@]} -gt 0 ]]; then
    args+=("${auth_header[@]}")
  fi
  args+=(--output "$dest" "$url")
  curl "${args[@]}"
  # ensure a trailing newline after curl's progress bar
  echo ""
}

download "$SHA_URL" "$CHECKSUM_OUTPUT" "$CHECKSUM_NAME"
download "$IMG_URL" "$OUTPUT" "$ASSET_NAME"

if command -v sha256sum >/dev/null 2>&1; then
  IMAGE_SUM=$(sha256sum "$OUTPUT" | awk '{print $1}')
else
  IMAGE_SUM=$(shasum -a 256 "$OUTPUT" | awk '{print $1}')
fi
EXPECTED_SUM=$(awk 'NF >= 1 {print $1; exit}' "$CHECKSUM_OUTPUT")

if [[ -z "$EXPECTED_SUM" ]]; then
  echo "checksum file $CHECKSUM_OUTPUT did not contain a digest" >&2
  exit 1
fi

if [[ "$IMAGE_SUM" != "$EXPECTED_SUM" ]]; then
  echo "checksum mismatch for $OUTPUT" >&2
  exit 1
fi

printf '%s  %s\n' "$EXPECTED_SUM" "$(basename "$OUTPUT")" >"$CHECKSUM_OUTPUT"

trap - EXIT

echo "✅ Downloaded release ${TAG_NAME:-$TAG}"
ls -lh "$OUTPUT" "$CHECKSUM_OUTPUT"
echo "Image saved to $OUTPUT with checksum $CHECKSUM_OUTPUT"
