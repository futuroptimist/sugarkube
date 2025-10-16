#!/usr/bin/env bash
set -euo pipefail
pattern="libraspberrypi-""bin"
if grep -R --line-number --fixed-strings "${pattern}" scripts .github/workflows tests \
     --exclude-dir='.git' --exclude='tests/no_libraspberrypi_bin_test.sh'; then
  echo "Found forbidden package '${pattern}' in repo" >&2
  exit 1
fi
