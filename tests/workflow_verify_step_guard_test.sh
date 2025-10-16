#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image.yml"
# Require the exact gating expression to prevent accidental regressions.
grep -F "if: \${{ always() && !cancelled() && hashFiles('deploy/**') != '' }}" "$wf" >/dev/null
