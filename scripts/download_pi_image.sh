#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

err() {
  printf 'ERROR: %s\n' "$*" >&2
}

die() {
  err "$1"
  exit "${2:-1}"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [ -n "${2:-}" ]; then
      die "$2"
    else
      die "Missing required command: $1"
    fi
  fi
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "python3"
  elif command -v python >/dev/null 2>&1; then
    printf '%s' "python"
  else
    die "python3 (or python) is required to parse release metadata"
  fi
}

usage() {
  cat <<'USAGE'
Download the latest sugarkube Pi image release artifact and verify its checksum.

Usage: download_pi_image.sh [options] [OUTPUT]

Options:
  -o, --output PATH     Write the image to PATH (default:
                        ~/sugarkube/images/sugarkube.img.xz)
      --dir DIR         Store downloads in DIR (default: $HOME/sugarkube/images)
      --release TAG     Download a specific release tag instead of the latest
      --asset NAME      Override the image asset name (default: sugarkube.img.xz)
      --checksum NAME   Override the checksum asset name (default: asset + .sha256)
      --mode MODE       Force download mode: release, workflow, or auto (default)
  -h, --help            Show this message

Environment:
  SUGARKUBE_OWNER           Override GitHub owner (default: futuroptimist)
  SUGARKUBE_REPO            Override repository (default: sugarkube)
  SUGARKUBE_IMAGE_DIR       Override default destination directory
  SUGARKUBE_IMAGE_ASSET     Override default asset name
  SUGARKUBE_CHECKSUM_ASSET  Override default checksum asset name
  SUGARKUBE_DOWNLOAD_MODE   Default mode when --mode is not provided
USAGE
}

OWNER="${SUGARKUBE_OWNER:-futuroptimist}"
REPO="${SUGARKUBE_REPO:-sugarkube}"
DEFAULT_ASSET="${SUGARKUBE_IMAGE_ASSET:-sugarkube.img.xz}"
DEFAULT_CHECKSUM="${SUGARKUBE_CHECKSUM_ASSET:-${DEFAULT_ASSET}.sha256}"
DEFAULT_DIR="${SUGARKUBE_IMAGE_DIR:-$HOME/sugarkube/images}"
MODE="${SUGARKUBE_DOWNLOAD_MODE:-auto}"
RELEASE_TAG=""
DEST_ARG=""
DEST_DIR_OVERRIDE=""
ASSET_NAME="$DEFAULT_ASSET"
CHECKSUM_NAME="$DEFAULT_CHECKSUM"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -o|--output)
      DEST_ARG="$2"; shift 2 ;;
    --dir)
      DEST_DIR_OVERRIDE="$2"; shift 2 ;;
    --release)
      RELEASE_TAG="$2"; shift 2 ;;
    --asset)
      ASSET_NAME="$2"; shift 2 ;;
    --checksum)
      CHECKSUM_NAME="$2"; shift 2 ;;
    --mode)
      MODE="$2"; shift 2 ;;
    --)
      shift; break ;;
    -*)
      die "Unknown option: $1" ;;
    *)
      if [ -n "$DEST_ARG" ]; then
        die "Unexpected positional argument: $1"
      fi
      DEST_ARG="$1"; shift ;;
  esac
done

case "$MODE" in
  auto|release|workflow) ;;
  *) die "Unsupported mode '$MODE' (expected auto, release, or workflow)" ;;
esac

if [ -n "$RELEASE_TAG" ] && [ "$MODE" = "workflow" ]; then
  die "--release cannot be used with --mode workflow"
fi

require_cmd gh "gh is required"
require_cmd curl "curl is required to download release assets"
require_cmd sha256sum "sha256sum is required to verify downloads"
PYTHON_BIN="$(find_python)"

if [ -n "$DEST_ARG" ]; then
  DEST_PATH="$DEST_ARG"
  DEST_DIRNAME="$(dirname "$DEST_PATH")"
else
  DEST_DIRNAME="${DEST_DIR_OVERRIDE:-$DEFAULT_DIR}"
  DEST_PATH="${DEST_DIRNAME%/}/$ASSET_NAME"
fi

CHECKSUM_PATH="${DEST_PATH}.sha256"
mkdir -p "$DEST_DIRNAME"

AUTH_HEADER=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_HEADER="Authorization: token ${GITHUB_TOKEN}"
elif TOKEN_VALUE=$(gh auth token 2>/dev/null); then
  [ -n "$TOKEN_VALUE" ] && AUTH_HEADER="Authorization: token ${TOKEN_VALUE}"
fi

trim_hash() {
  awk 'NF >= 1 { gsub(/\r/, "", $1); print tolower($1); exit }' "$1"
}

verify_checksum() {
  local file="$1" checksum_file="$2"
  [ ! -f "$checksum_file" ] && die "Checksum file '$checksum_file' not found"
  local expected actual
  expected="$(trim_hash "$checksum_file")"
  [ -z "$expected" ] && die "Checksum file '$checksum_file' did not contain a hash"
  actual="$(sha256sum "$file" | awk '{print tolower($1)}')"
  [ "$actual" != "$expected" ] && die "Checksum mismatch. Expected $expected but got $actual"
  log "Checksum verified ($actual)"
}

download_with_curl() {
  local url="$1" destination="$2" label="$3"
  local partial="${destination}.partial"
  local -a args=(--fail --location --retry 5 --retry-delay 5 --retry-connrefused -C - --progress-bar --output "$partial")
  [ -n "$AUTH_HEADER" ] && args+=(--header "$AUTH_HEADER")
  args+=("$url")
  log "Downloading $label"
  curl "${args[@]}" || die "Download failed for $label"
  mv "$partial" "$destination"
}

parse_release_json() {
  local asset="$1" checksum="$2"
  "$PYTHON_BIN" -c 'import json, sys
asset, checksum = sys.argv[1], sys.argv[2]
data = json.load(sys.stdin)
def find(name):
  for a in data.get("assets", []):
    if a.get("name") == name:
      return a.get("browser_download_url") or a.get("url") or ""
  return ""
print(find(asset)); print(find(checksum)); print(data.get("tag_name") or data.get("name") or "")' "$asset" "$checksum"
}

download_from_release() {
  local endpoint="repos/${OWNER}/${REPO}/releases/${RELEASE_TAG:+tags/}${RELEASE_TAG:-latest}"
  release_payload=$(gh api "$endpoint" 2>/dev/null) || return 1
  mapfile -t info < <(printf '%s' "$release_payload" | parse_release_json "$ASSET_NAME" "$CHECKSUM_NAME")
  local asset_url="${info[0]}" checksum_url="${info[1]}" tag="${info[2]}"
  [ -z "$asset_url" ] && return 1
  log "Resolved release ${tag:-latest}"
  download_with_curl "$asset_url" "$DEST_PATH" "$ASSET_NAME"
  [ -z "$checksum_url" ] && die "Release ${tag:-latest} missing $CHECKSUM_NAME"
  download_with_curl "$checksum_url" "$CHECKSUM_PATH" "$CHECKSUM_NAME"
  verify_checksum "$DEST_PATH" "$CHECKSUM_PATH"
}

download_from_workflow() {
  log "Falling back to latest successful pi-image workflow artifact"
  run_id=$(gh run list --workflow pi-image.yml --branch main --json databaseId -q '.[0].databaseId') || die "no pi-image workflow runs found"
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' RETURN
  gh run download "$run_id" --name sugarkube-img --dir "$tmp_dir" || die "Failed to download workflow artifact"
  mv "$tmp_dir/sugarkube.img.xz" "$DEST_PATH"
  mv "$tmp_dir/sugarkube.img.xz.sha256" "$CHECKSUM_PATH"
  verify_checksum "$DEST_PATH" "$CHECKSUM_PATH"
}

success=0
if [ "$MODE" = "release" ] || [ "$MODE" = "auto" ]; then
  download_from_release && success=1 || [ "$MODE" = "release" ] && die "Failed to download release asset"
fi
if [ "$success" -eq 0 ] && { [ "$MODE" = "workflow" ] || [ "$MODE" = "auto" ]; }; then
  download_from_workflow && success=1
fi

log "Image saved to $DEST_PATH"
[ -f "$CHECKSUM_PATH" ] && log "Checksum saved to $CHECKSUM_PATH"
ls -lh "$DEST_PATH" "$CHECKSUM_PATH" 2>/dev/null || true
