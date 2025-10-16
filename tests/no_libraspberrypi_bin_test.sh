#!/usr/bin/env bash
set -euo pipefail
if grep -R --line-number --fixed-strings 'libraspberrypi-bin' \
     --exclude='*.md' \
     scripts .github/workflows tests | \
     grep -v 'tests/no_libraspberrypi_bin_test.sh'; then
  echo "Found forbidden package 'libraspberrypi-bin' in repo" >&2
  exit 1
fi
