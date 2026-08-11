#!/usr/bin/env bash
# Strictly read-only wrapper. The Python collector enforces an internal command allowlist.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "${ROOT}/scripts/prod_resilience_audit.py" "$@"
