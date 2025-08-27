#!/usr/bin/env bash
set -euo pipefail

# Download the latest sugarkube Pi image artifact via the GitHub CLI.
# Requires the GitHub CLI to be authenticated with access to this repository.

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required" >&2
  exit 1
fi

OUTPUT="${1:-sugarkube.img.xz}"
if [ -d "$OUTPUT" ] || [[ "$OUTPUT" == */ ]]; then
  OUTPUT="${OUTPUT%/}/sugarkube.img.xz"
fi

RUN_ID=$(gh run list --workflow pi-image.yml --branch main --json databaseId -q '.[0].databaseId')
if [ -z "$RUN_ID" ]; then
  echo "no pi-image workflow runs found" >&2
  exit 1
fi

dirname=$(dirname "$OUTPUT")
mkdir -p "$dirname"

gh run download "$RUN_ID" --name sugarkube-img --dir "$dirname"

src="$dirname/sugarkube.img.xz"
if [ "$src" != "$OUTPUT" ]; then
  mv "$src" "$OUTPUT"
fi
ls -lh "$OUTPUT"
echo "Image saved to $OUTPUT"
