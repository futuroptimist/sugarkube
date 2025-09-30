#!/usr/bin/env bash
set -euo pipefail

find_python() {
  if [ -n "${SUGARKUBE_PYTHON:-}" ]; then
    echo "$SUGARKUBE_PYTHON"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    echo python3
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    echo python
    return 0
  fi

  echo "Unable to find a Python interpreter for sugarkube_toolkit." >&2
  return 1
}

print_notice() {
  cat <<'MSG' >&2
[DEPRECATED] scripts/docs_verify.sh will be removed once callers migrate to "python -m sugarkube_toolkit docs verify".
Forwarding to the unified CLI—update your workflow to call it directly.
MSG
}

print_notice
PYTHON_INTERPRETER="$(find_python)"

exec "$PYTHON_INTERPRETER" -m sugarkube_toolkit docs verify "$@"
