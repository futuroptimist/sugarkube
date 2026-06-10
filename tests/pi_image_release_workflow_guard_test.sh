#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image-release.yml"

# The signed release publisher is intentionally manual so unrelated main merges
# and scheduled runs do not repeatedly execute the expensive image release path.
grep -F "workflow_dispatch:" "$wf" >/dev/null
if grep -Eq '^  (push|schedule):' "$wf"; then
  echo "pi-image-release.yml must remain manual-only unless path gating is added intentionally" >&2
  exit 1
fi

# Cleanup must not remove the runner toolcache; later JavaScript actions need Node.
if grep -F "/opt/hostedtoolcache" "$wf" >/dev/null; then
  echo "pi-image-release.yml must not delete /opt/hostedtoolcache" >&2
  exit 1
fi
grep -F "Verify Node runtime availability" "$wf" >/dev/null
grep -F "node --version" "$wf" >/dev/null

# Release runs should share the maintained pi-gen cache-key helper and keep publish explicit.
grep -F "scripts/compute_pi_gen_cache_key.sh" "$wf" >/dev/null
grep -F "publish_release:" "$wf" >/dev/null
grep -F "if: env.PUBLISH_RELEASE == 'true'" "$wf" >/dev/null
