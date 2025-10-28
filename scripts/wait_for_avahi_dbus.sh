#!/bin/sh
# shellcheck disable=SC3040,SC3041,SC3043
set -eu

if (set -o pipefail) 2>/dev/null; then
  set -o pipefail
fi

if (set -E) 2>/dev/null; then
  set -E
fi

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/log.sh
. "${SCRIPT_DIR}/log.sh"

if ! command -v gdbus >/dev/null 2>&1; then
  log_info avahi_dbus_ready outcome=skip reason=gdbus_missing
  exit 2
fi

wait_limit_ms="${AVAHI_DBUS_WAIT_MS:-4000}"
case "${wait_limit_ms}" in
  ''|*[!0-9]*) wait_limit_ms=4000 ;;
  *)
    if [ "${wait_limit_ms}" -lt 0 ]; then
      wait_limit_ms=0
    fi
    ;;
esac

script_start_ms="$(python3 - <<'PY'
import time
print(int(time.time() * 1000))
PY
)"

elapsed_since_start_ms() {
  python3 - "$@" <<'PY'
import sys
import time

try:
    start = int(sys.argv[1])
except (IndexError, ValueError):
    start = 0
now = int(time.time() * 1000)
elapsed = now - start
if elapsed < 0:
    elapsed = 0
print(elapsed)
PY
}

while :; do
  if gdbus introspect \
    --system \
    --dest org.freedesktop.Avahi \
    --object-path /org/freedesktop/Avahi/Server \
    --timeout 1 >/dev/null 2>&1; then
    elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
    log_info avahi_dbus_ready outcome=ok ms_elapsed="${elapsed_ms}"
    exit 0
  fi

  elapsed_ms="$(elapsed_since_start_ms "${script_start_ms}")"
  if [ "${elapsed_ms}" -ge "${wait_limit_ms}" ]; then
    log_info avahi_dbus_ready outcome=timeout ms_elapsed="${elapsed_ms}"
    exit 1
  fi

  sleep 0.1

done
