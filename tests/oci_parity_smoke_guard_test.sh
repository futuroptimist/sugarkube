#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image.yml"

# Ensure the new OCI parity smoke job and its key checks remain present.
grep -F "oci-parity-smoke:" "$wf" >/dev/null
grep -F "docker/setup-buildx-action@v3" "$wf" >/dev/null
grep -F "dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36" "$wf" >/dev/null
grep -F "docker buildx build" "$wf" >/dev/null
grep -F "require('canvas'); console.log('canvas ok')" "$wf" >/dev/null
grep -F "Checking \${path} on \${platform}" "$wf" >/dev/null
# Verify the docs parity probes stay in place.
grep -F "\"/docs\" \"/docs/dCarbon\"" "$wf" >/dev/null
grep -F "dCarbon represents the amount of carbon dioxide produced by a player" "$wf" >/dev/null
