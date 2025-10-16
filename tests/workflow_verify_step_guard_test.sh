#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image.yml"
# Require the exact gating expression to prevent accidental regressions.
pattern="if: \$\{\{ always() && !cancelled() && hashFiles('deploy/**') != '' \}\}"
grep -F "$pattern" "$wf" >/dev/null
