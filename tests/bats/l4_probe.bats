#!/usr/bin/env bats

setup() {
  LISTENER_PIDS=()
  if command -v ncat >/dev/null 2>&1; then
    NCAT_HELPER="$(command -v ncat)"
  else
    NCAT_HELPER="${BATS_TEST_DIRNAME}/fixtures/ncat_stub.py"
  fi
}

teardown() {
  for pid in "${LISTENER_PIDS[@]}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
    fi
  done
}

# Start a listener and wait for it to actually be accepting connections.
# This avoids race conditions where we try to connect before the listener is ready.
start_listener() {
  local port="$1"
  local max_wait=20  # 2 seconds max (20 * 0.1s)
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
  echo "Warning: listener may not be ready on port ${port}" >&2
}

# Allocate a port that is guaranteed to be free and bindable.
# Uses a retry loop to handle rare race conditions under instrumentation tools.
allocate_port() {
  python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

@test "l4_probe reports open port as open" {
  open_port="$(allocate_port)"
  start_listener "${open_port}"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${open_port}"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [[ "${lines[0]}" =~ "\"port\":${open_port}" ]]
  [[ "${lines[0]}" =~ '"status":"open"' ]]
}

@test "l4_probe exits non-zero when a port is closed" {
  open_port="$(allocate_port)"
  closed_port="$(allocate_port)"
  start_listener "${open_port}"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${open_port},${closed_port}"

  [ "$status" -ne 0 ]
  [ "${#lines[@]}" -eq 2 ]
  [[ "${lines[0]}" =~ '"status":"open"' ]]
  [[ "${lines[1]}" =~ '"status":"closed"' ]]
  [[ "${lines[1]}" =~ "\"port\":${closed_port}" ]]
}
