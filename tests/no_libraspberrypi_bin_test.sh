#!/usr/bin/env bash
set -euo pipefail
needle="libraspberrypi-""bin"
if grep -R --line-number --fixed-strings \
     --exclude='*.md' \
     "${needle}" \
     scripts .github/workflows tests; then
  echo "Found forbidden package '${needle}' in repo" >&2
  exit 1
fi
