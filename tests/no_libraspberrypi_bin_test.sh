#!/usr/bin/env bash
set -euo pipefail
if grep -R --line-number --fixed-strings 'libraspberrypi-bin' \
     scripts .github/workflows \
     --exclude='*.md' ; then
  echo "Found forbidden package 'libraspberrypi-bin' in repo" >&2
  exit 1
fi
