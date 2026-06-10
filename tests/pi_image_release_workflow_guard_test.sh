#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image-release.yml"

# The release publisher must stay intentionally manual so unrelated main merges
# and nightly windows do not run the expensive signed image build.
grep -F "workflow_dispatch:" "$wf" >/dev/null
if grep -Eq '^  (push|schedule):' "$wf"; then
  echo "pi-image-release.yml must not run on push or schedule without an explicit guard update" >&2
  exit 1
fi

# Disk cleanup must not remove the hosted toolcache because later JavaScript
# actions need a working Node runtime.
if grep -F "/opt/hostedtoolcache" "$wf" >/dev/null; then
  echo "pi-image-release.yml must not delete /opt/hostedtoolcache" >&2
  exit 1
fi
grep -F "Verify Node runtime availability" "$wf" >/dev/null

# Keep the release workflow aligned with the canonical pi-gen cache helper and
# make release publication an explicit dispatch choice.
grep -F "scripts/compute_pi_gen_cache_key.sh" "$wf" >/dev/null
grep -F "publish_release:" "$wf" >/dev/null
grep -F "if: env.PUBLISH_RELEASE == 'true'" "$wf" >/dev/null
grep -F "run_qemu_smoke:" "$wf" >/dev/null
grep -F "if: env.RUN_QEMU_SMOKE == 'true'" "$wf" >/dev/null
