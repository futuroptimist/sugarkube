#!/usr/bin/env bash
# Common helper functions for l4_probe tests.

# Start a listener and wait for it to actually be accepting connections.
# This avoids race conditions where we try to connect before the listener is ready.
# Fails the test immediately if the listener does not start in time.
start_listener() {
  local port="$1"
  local max_wait="${2:-20}"  # 2 seconds max by default (20 * 0.1s)
  local i=0

  "${NCAT_HELPER}" -lk 127.0.0.1 "${port}" >/dev/null 2>&1 &
  LISTENER_PIDS+=("$!")

  # Wait until the port is actually accepting connections
  while [ $i -lt $max_wait ]; do
    if python3 -c "import socket; s=socket.socket(); s.settimeout(0.05); s.connect(('127.0.0.1', ${port})); s.close()" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
    i=$((i + 1))
  done
  fail "listener did not start on port ${port} after ${max_wait} attempts"
}

# Allocate a port that is guaranteed to be free.
allocate_port() {
  python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}
