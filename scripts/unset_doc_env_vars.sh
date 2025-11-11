#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOC_PATH_DEFAULT="${SCRIPT_DIR}/../docs/raspi_cluster_setup.md"
DOC_PATH="${SUGARKUBE_RASPI_SETUP_DOC:-${DOC_PATH_DEFAULT}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

fallback_vars=(
    "K3S_CHANNEL"
    "SAVE_DEBUG_LOGS"
    "SUGARKUBE_API_REGADDR"
    "SUGARKUBE_CLUSTER"
    "SUGARKUBE_DEBUG_MDNS"
    "SUGARKUBE_ENV"
    "SUGARKUBE_FIX_TIME"
    "SUGARKUBE_MDNS_WIRE_PROOF"
    "SUGARKUBE_SERVERS"
    "SUGARKUBE_STRICT_TIME"
    "SUGARKUBE_TOKEN"
    "SUGARKUBE_TOKEN_DEV"
    "SUGARKUBE_TOKEN_INT"
    "SUGARKUBE_TOKEN_PROD"
)

if python_output="$(${PYTHON_BIN} - "${DOC_PATH}" <<'PY' 2>/dev/null
import re
import sys
from pathlib import Path

if len(sys.argv) < 2:
    raise SystemExit(1)

doc_path = Path(sys.argv[1])
if not doc_path.is_file():
    raise SystemExit(1)

text = doc_path.read_text(encoding="utf-8")
pattern = re.compile(r"\b(?:SUGARKUBE|SAVE_DEBUG_LOGS|K3S_CHANNEL)[A-Z0-9_]*\b")
raw = {match.strip("`\"") for match in pattern.findall(text)}
raw.discard("SUGARKUBE")
raw.discard("")
for name in sorted(raw):
    print(name)
PY
)"; then
    if [ -n "${python_output}" ]; then
        readarray -t DOC_ENV_VARS <<< "${python_output}"
    else
        DOC_ENV_VARS=("${fallback_vars[@]}")
    fi
else
    DOC_ENV_VARS=("${fallback_vars[@]}")
fi

if [ "${#DOC_ENV_VARS[@]}" -eq 0 ]; then
    exit 0
fi

unset_vars=()
for var_name in "${DOC_ENV_VARS[@]}"; do
    if [ -z "${var_name}" ]; then
        continue
    fi
    if [ "${!var_name-UNSET}" != "UNSET" ]; then
        unset "${var_name}"
        unset_vars+=("${var_name}")
    fi
done

if [ -n "${XDG_CACHE_HOME:-}" ]; then
    cleanup_dir="${XDG_CACHE_HOME}"
else
    cleanup_dir="${HOME:-}"
    if [ -n "${cleanup_dir}" ]; then
        cleanup_dir="${cleanup_dir%/}/.cache"
    fi
fi
cleanup_snippet=""
if [ -n "${cleanup_dir}" ]; then
    cleanup_dir="${cleanup_dir%/}/sugarkube"
    cleanup_snippet="${cleanup_dir}/wipe-env.sh"
    if mkdir -p "${cleanup_dir}" 2>/dev/null; then
        {
            printf '#!/usr/bin/env bash\n'
            printf 'set -euo pipefail\n'
            for var_name in "${DOC_ENV_VARS[@]}"; do
                if [ -n "${var_name}" ]; then
                    printf 'unset %s\n' "${var_name}"
                fi
            done
        } >"${cleanup_snippet}" 2>/dev/null || true
        chmod +x "${cleanup_snippet}" 2>/dev/null || true
    else
        cleanup_snippet=""
    fi
fi

if [ "${#unset_vars[@]}" -gt 0 ]; then
    printf 'Unset environment variables: %s\n' "${unset_vars[*]}"
else
    printf 'No documented Sugarkube environment variables were set.\n'
fi

if [ -n "${cleanup_snippet}" ]; then
    printf 'Shell cleanup snippet written to %s\n' "${cleanup_snippet}"
fi
