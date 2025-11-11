#!/usr/bin/env bats

setup() {
  LISTENER_PIDS=()
  if command -v ncat >/dev/null 2>&1; then
    NCAT_AVAILABLE=1
  else
    NCAT_AVAILABLE=0
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

start_listener() {
  local port="$1"
  ncat -lk 127.0.0.1 "${port}" >/dev/null 2>&1 &
  LISTENER_PIDS+=("$!")
  # Give the listener a moment to start accepting connections.
  sleep 0.1
}

allocate_port() {
  python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

@test "l4_probe reports open port as open" {
  if [ "${NCAT_AVAILABLE}" -ne 1 ]; then
    # TODO: Install ncat or provide a stub so port probing exercises real sockets.
    # Root cause: Minimal hosts skip the test because the nmap-ncat package is absent.
    # Estimated fix: 10m to install nmap-ncat or extend the test harness with a fake binary.
    skip "ncat not available"
  fi
  open_port="$(allocate_port)"
  start_listener "${open_port}"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${open_port}"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [[ "${lines[0]}" =~ "\"port\":${open_port}" ]]
  [[ "${lines[0]}" =~ '"status":"open"' ]]
}

@test "l4_probe exits non-zero when a port is closed" {
  if [ "${NCAT_AVAILABLE}" -ne 1 ]; then
    # TODO: Install ncat or provide a stub so port probing exercises real sockets.
    # Root cause: Minimal hosts skip the test because the nmap-ncat package is absent.
    # Estimated fix: 10m to install nmap-ncat or extend the test harness with a fake binary.
    skip "ncat not available"
  fi
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
