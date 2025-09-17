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
DRY_RUN=0
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
      if [ "$#" -lt 2 ]; then
        die "--output requires a value"
      fi
      DEST_ARG="$2"
      shift 2
      ;;
    --dir)
      if [ "$#" -lt 2 ]; then
        die "--dir requires a value"
      fi
      DEST_DIR_OVERRIDE="$2"
      shift 2
      ;;
    --release)
      if [ "$#" -lt 2 ]; then
        die "--release requires a value"
      fi
      RELEASE_TAG="$2"
      shift 2
      ;;
    --asset)
      if [ "$#" -lt 2 ]; then
        die "--asset requires a value"
      fi
      ASSET_NAME="$2"
      shift 2
      ;;
    --checksum)
      if [ "$#" -lt 2 ]; then
        die "--checksum requires a value"
      fi
      CHECKSUM_NAME="$2"
      shift 2
      ;;
    --mode)
      if [ "$#" -lt 2 ]; then
        die "--mode requires a value"
      fi
      MODE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "Unknown option: $1"
      ;;
    *)
      if [ -n "$DEST_ARG" ]; then
        die "Unexpected positional argument: $1"
      fi
      DEST_ARG="$1"
      shift
      ;;
  esac
done

case "$MODE" in
  auto|release|workflow)
    ;;
  *)
    die "Unsupported mode '$MODE' (expected auto, release, or workflow)"
    ;;
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
  if [ -n "$DEST_DIR_OVERRIDE" ]; then
    DEST_DIRNAME="$DEST_DIR_OVERRIDE"
  else
    DEST_DIRNAME="$DEFAULT_DIR"
  fi
  DEST_PATH="${DEST_DIRNAME%/}/$ASSET_NAME"
fi

CHECKSUM_PATH="${DEST_PATH}.sha256"
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$DEST_DIRNAME"
fi

AUTH_HEADER=""
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_HEADER="Authorization: token ${GITHUB_TOKEN}"
else
  if TOKEN_VALUE=$(gh auth token 2>/dev/null); then
    if [ -n "$TOKEN_VALUE" ]; then
      AUTH_HEADER="Authorization: token ${TOKEN_VALUE}"
    fi
  fi
fi

trim_hash() {
  awk 'NF >= 1 { gsub(/\r/, "", $1); print tolower($1); exit }' "$1"
}

verify_checksum() {
  local file="$1"
  local checksum_file="$2"
  if [ ! -f "$checksum_file" ]; then
    die "Checksum file '$checksum_file' was not downloaded"
  fi
  local expected
  expected="$(trim_hash "$checksum_file")"
  if [ -z "$expected" ]; then
    die "Checksum file '$checksum_file' did not contain a hash"
  fi
  local actual
  actual="$(sha256sum "$file" | awk '{print tolower($1)}')"
  if [ "$actual" != "$expected" ]; then
    err "Checksum mismatch. Expected $expected but calculated $actual"
    return 1
  fi
  log "Checksum verified ($actual)"
}

download_with_curl() {
  local url="$1"
  local destination="$2"
  local label="$3"
  local partial="${destination}.partial"
  local -a args
  args=(--fail --location --retry 5 --retry-delay 5 --retry-connrefused -C - --progress-bar --output "$partial")
  if [ -n "$AUTH_HEADER" ] && [[ "$url" != file://* ]]; then
    args+=(--header "$AUTH_HEADER")
  fi
  args+=("$url")
  log "Downloading $label"
  if ! curl "${args[@]}"; then
    err "Download failed for $label"
    return 1
  fi
  if [ ! -f "$partial" ]; then
    err "Download did not produce expected file: $partial"
    return 1
  fi
  mv "$partial" "$destination"
}

parse_release_json() {
  local asset="$1"
  local checksum="$2"
  "$PYTHON_BIN" -c 'import json, sys
asset_name = sys.argv[1]
checksum_name = sys.argv[2]
data = json.load(sys.stdin)

def find_asset(name):
    for candidate in data.get("assets", []):
        if candidate.get("name") == name:
            return candidate.get("browser_download_url") or candidate.get("url") or ""
    return ""

asset_url = find_asset(asset_name)
checksum_url = find_asset(checksum_name)
tag = data.get("tag_name") or data.get("name") or ""
print(asset_url)
print(checksum_url)
print(tag)
' "$asset" "$checksum"
}

download_from_release() {
  local endpoint
  if [ -n "$RELEASE_TAG" ]; then
    endpoint="repos/${OWNER}/${REPO}/releases/tags/${RELEASE_TAG}"
  else
    endpoint="repos/${OWNER}/${REPO}/releases/latest"
  fi
  if ! release_payload=$(gh api "$endpoint" 2>/dev/null); then
    return 1
  fi
  if ! mapfile -t release_info < <(printf '%s' "$release_payload" | parse_release_json "$ASSET_NAME" "$CHECKSUM_NAME"); then
    return 1
  fi
  local asset_url="${release_info[0]:-}"
  local checksum_url="${release_info[1]:-}"
  local tag_name="${release_info[2]:-}"
  if [ -z "$asset_url" ]; then
    return 1
  fi
  log "Resolved release ${tag_name:-latest}"
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ -z "$checksum_url" ]; then
      die "Release ${tag_name:-latest} did not include ${CHECKSUM_NAME}"
    fi
    log "Dry run: would download $ASSET_NAME to $DEST_PATH"
    log "Dry run: would download $CHECKSUM_NAME to $CHECKSUM_PATH"
    return 0
  fi
  if ! download_with_curl "$asset_url" "$DEST_PATH" "$ASSET_NAME"; then
    return 1
  fi
  if [ -z "$checksum_url" ]; then
    die "Release ${tag_name:-latest} did not include ${CHECKSUM_NAME}"
  fi
  if ! download_with_curl "$checksum_url" "$CHECKSUM_PATH" "$CHECKSUM_NAME"; then
    return 1
  fi
  verify_checksum "$DEST_PATH" "$CHECKSUM_PATH"
}

download_from_workflow() {
  log "Falling back to latest successful pi-image workflow artifact"
  local run_id
  run_id=$(gh run list --workflow pi-image.yml --branch main --json databaseId -q '.[0].databaseId') || run_id=""
  if [ -z "$run_id" ]; then
    die "no pi-image workflow runs found"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run: workflow run $run_id provides sugarkube.img.xz"
    return 0
  fi
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir}"' RETURN
  if ! gh run download "$run_id" --name sugarkube-img --dir "$tmp_dir"; then
    die "Failed to download workflow artifact"
  fi
  local artifact_img="$tmp_dir/sugarkube.img.xz"
  local artifact_sha="$tmp_dir/sugarkube.img.xz.sha256"
  if [ ! -f "$artifact_img" ]; then
    die "Workflow artifact missing sugarkube.img.xz"
  fi
  mv "$artifact_img" "$DEST_PATH"
  if [ -f "$artifact_sha" ]; then
    mv "$artifact_sha" "$CHECKSUM_PATH"
    verify_checksum "$DEST_PATH" "$CHECKSUM_PATH"
  else
    die "Workflow artifact missing checksum"
  fi
  rm -rf "$tmp_dir"
  trap - RETURN
}

success=0
if [ "$MODE" = "release" ] || [ "$MODE" = "auto" ]; then
  if download_from_release; then
    success=1
  elif [ "$MODE" = "release" ]; then
    die "Failed to download release asset"
  fi
fi

if [ "$success" -eq 0 ]; then
  if [ "$MODE" = "workflow" ] || [ "$MODE" = "auto" ]; then
    download_from_workflow || die "Failed to download workflow artifact"
    success=1
  fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "Dry run complete. No files were downloaded."
  exit 0
fi

log "Image saved to $DEST_PATH"
if [ -f "$CHECKSUM_PATH" ]; then
  log "Checksum saved to $CHECKSUM_PATH"
fi
ls -lh "$DEST_PATH" "$CHECKSUM_PATH" 2>/dev/null || true
