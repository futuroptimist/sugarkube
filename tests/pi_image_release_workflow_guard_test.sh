#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image-release.yml"
empty=""

# The release publisher must stay intentionally dispatched rather than running on every merge.
grep -F '"on":' "$wf" >/dev/null
grep -F "workflow_dispatch:" "$wf" >/dev/null
if grep -Eq '^  (push|schedule):' "$wf"; then
  echo "pi-image-release.yml must not define automatic push or schedule triggers" >&2
  exit 1
fi

# Keep runner cleanup compatible with later JavaScript actions.
if grep -Fq "/opt/hosted${empty}toolcache" "$wf"; then
  echo "pi-image-release.yml must not delete /opt/hosted${empty}toolcache" >&2
  exit 1
fi
grep -F "Verify Node runtime availability" "$wf" >/dev/null

# Keep release runs configurable without weakening the default signed release path.
grep -F "release_channel:" "$wf" >/dev/null
grep -F "publish_release:" "$wf" >/dev/null
grep -F "run_qemu_smoke:" "$wf" >/dev/null
grep -F "PUBLISH_RELEASE: \${{ inputs.publish_release == false && 'false' || 'true' }}" "$wf" >/dev/null
grep -F "RUN_QEMU_SMOKE: \${{ inputs.run_qemu_smoke == false && 'false' || 'true' }}" "$wf" >/dev/null
grep -F "if: env.PUBLISH_RELEASE != 'false'" "$wf" >/dev/null
grep -F "if: env.RUN_QEMU_SMOKE != 'false'" "$wf" >/dev/null

# Reuse the shared cache-key helper rather than duplicating fragile git/date logic.
grep -F "bash scripts/compute_pi_gen_cache_key.sh" "$wf" >/dev/null

# Ensure pi-image guard jobs trigger when the release workflow changes.
pi_wf=".github/workflows/pi-image.yml"
release_path_count=$(grep -Fc "'.github/workflows/pi-image-release.yml'" "$pi_wf")
if [ "$release_path_count" -lt 2 ]; then
  echo "pi-image.yml must include pi-image-release.yml in pull_request path filters" >&2
  exit 1
fi
