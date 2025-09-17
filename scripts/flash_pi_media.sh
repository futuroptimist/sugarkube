#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required to run flash_pi_media" >&2
  exit 1
fi

exec python3 "$SCRIPT_DIR/flash_pi_media.py" "$@"
