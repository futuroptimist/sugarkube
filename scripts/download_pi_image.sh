#!/usr/bin/env bash
set -euo pipefail

# Download the latest sugarkube Pi image artifact via the GitHub CLI.
# Requires the GitHub CLI to be authenticated with access to this repository.

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required" >&2
  exit 1
fi

OUTPUT="${1:-sugarkube.img.xz}"

RUN_ID=$(gh run list --workflow pi-image.yml --branch main --json databaseId -q '.[0].databaseId')
if [ -z "$RUN_ID" ]; then
  echo "no pi-image workflow runs found" >&2
  exit 1
fi

dirname=$(dirname "$OUTPUT")
mkdir -p "$dirname"

gh run download "$RUN_ID" --name sugarkube-img --dir "$dirname"
img="$dirname/sugarkube.img.xz"
sha="$dirname/sugarkube.img.xz.sha256"

if [ "$(realpath "$img")" != "$(realpath "$OUTPUT")" ]; then
  mv "$img" "$OUTPUT"
fi
if [ -f "$sha" ]; then
  dest_sha="${OUTPUT}.sha256"
  if [ "$(realpath "$sha")" != "$(realpath "$dest_sha")" ]; then
    mv "$sha" "$dest_sha"
  fi
fi

if [ -f "${OUTPUT}.sha256" ]; then
  ls -lh "$OUTPUT" "${OUTPUT}.sha256"
  echo "Image saved to $OUTPUT with checksum ${OUTPUT}.sha256"
else
  ls -lh "$OUTPUT"
  echo "Image saved to $OUTPUT"
fi
