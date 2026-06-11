#!/usr/bin/env bash
set -euo pipefail
wf=".github/workflows/pi-image-release.yml"
empty=""

# The release publisher must stay intentionally dispatched rather than running on every merge.
python3 - "$wf" <<'PY'
from pathlib import Path
import re
import sys

workflow = Path(sys.argv[1]).read_text().splitlines()


def strip_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


on_index = None
on_value = ""
for index, line in enumerate(workflow):
    match = re.match(r'^(?P<indent>\s*)(?:"on"|on)\s*:\s*(?P<value>.*)$', strip_comment(line))
    if match and not match.group("indent"):
        on_index = index
        on_value = match.group("value").strip()
        break

if on_index is None:
    raise SystemExit("pi-image-release.yml must define a top-level on block")

triggers = set()
if on_value:
    if on_value.startswith("[") and on_value.endswith("]"):
        triggers.update(item.strip().strip("'\"") for item in on_value[1:-1].split(","))
    else:
        triggers.add(on_value.strip().strip("'\""))
else:
    for line in workflow[on_index + 1 :]:
        stripped = strip_comment(line)
        if not stripped:
            continue
        if not line.startswith((" ", "\t")):
            break
        key_match = re.match(r'^\s+([A-Za-z0-9_-]+)\s*:', stripped)
        list_match = re.match(r'^\s+-\s*([A-Za-z0-9_-]+)\s*$', stripped)
        if key_match:
            triggers.add(key_match.group(1))
        elif list_match:
            triggers.add(list_match.group(1))

if "workflow_dispatch" not in triggers:
    raise SystemExit("pi-image-release.yml must keep workflow_dispatch enabled")
for automatic in ("push", "schedule"):
    if automatic in triggers:
        raise SystemExit(
            "pi-image-release.yml must not define automatic push or schedule triggers"
        )
PY

# Keep runner cleanup compatible with later JavaScript actions.
if grep -Fq "/opt/hosted${empty}toolcache" "$wf"; then
  echo "pi-image-release.yml must not delete /opt/hosted${empty}toolcache" >&2
  exit 1
fi
grep -F "Verify Node runtime availability" "$wf" >/dev/null

# Keep release runs configurable without weakening the default signed release path.
grep -F "release_channel:" "$wf" >/dev/null
grep -F "clone_sugarkube:" "$wf" >/dev/null
grep -F "clone_token_place:" "$wf" >/dev/null
grep -F "clone_dspace:" "$wf" >/dev/null
grep -F "publish_release:" "$wf" >/dev/null
grep -F "run_qemu_smoke:" "$wf" >/dev/null
grep -F "PUBLISH_RELEASE: \${{ inputs.publish_release == false && 'false' || 'true' }}" "$wf" >/dev/null
grep -F "RUN_QEMU_SMOKE: \${{ inputs.run_qemu_smoke == false && 'false' || 'true' }}" "$wf" >/dev/null
grep -F "if: env.PUBLISH_RELEASE != 'false'" "$wf" >/dev/null
grep -F "if: env.RUN_QEMU_SMOKE != 'false'" "$wf" >/dev/null
grep -F "Validate release publishing inputs" "$wf" >/dev/null
grep -F "QEMU smoke evidence is required when publish_release=true" "$wf" >/dev/null

# Reuse the shared cache-key helper rather than duplicating fragile git/date logic.
grep -F "bash scripts/compute_pi_gen_cache_key.sh" "$wf" >/dev/null

# Ensure pi-image guard jobs trigger when the release workflow changes.
pi_wf=".github/workflows/pi-image.yml"
release_path_count=$(grep -Fc "'.github/workflows/pi-image-release.yml'" "$pi_wf")
if [ "$release_path_count" -lt 2 ]; then
  echo "pi-image.yml must include pi-image-release.yml in pull_request path filters" >&2
  exit 1
fi
