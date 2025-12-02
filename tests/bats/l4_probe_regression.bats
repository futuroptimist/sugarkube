#!/usr/bin/env bats
# Regression tests for l4_probe.sh to prevent future breakages.
# These tests validate edge cases and ensure consistent behavior.

load helpers/l4_probe_helpers

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

# Regression: l4_probe must output valid JSON on each line
@test "l4_probe outputs valid JSON for each port" {
  open_port="$(allocate_port)"
  start_listener "${open_port}"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${open_port}"

  [ "$status" -eq 0 ]
  # Validate JSON structure with python
  echo "${lines[0]}" | python3 -c "import sys, json; json.load(sys.stdin)"
}

# Regression: l4_probe must include all required fields in output
@test "l4_probe JSON contains host, port, status, latency_ms fields" {
  open_port="$(allocate_port)"
  start_listener "${open_port}"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${open_port}"

  [ "$status" -eq 0 ]
  # Check for required fields
  [[ "${lines[0]}" =~ '"host":"127.0.0.1"' ]]
  [[ "${lines[0]}" =~ "\"port\":${open_port}" ]]
  [[ "${lines[0]}" =~ '"status":"open"' ]]
  [[ "${lines[0]}" =~ '"latency_ms":' ]]
}

# Regression: l4_probe must handle multiple ports correctly
@test "l4_probe handles comma-separated port list" {
  port1="$(allocate_port)"
  port2="$(allocate_port)"
  start_listener "${port1}"
  start_listener "${port2}"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${port1},${port2}"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 2 ]
  [[ "${lines[0]}" =~ "\"port\":${port1}" ]]
  [[ "${lines[1]}" =~ "\"port\":${port2}" ]]
}

# Regression: l4_probe must exit with error code 1 when any port is closed
@test "l4_probe exit code is 1 when at least one port is closed" {
  open_port="$(allocate_port)"
  closed_port="$(allocate_port)"
  start_listener "${open_port}"
  # closed_port deliberately has no listener

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${open_port},${closed_port}"

  [ "$status" -eq 1 ]
}

# Regression: l4_probe must include error field for closed ports
@test "l4_probe includes error field for closed port" {
  closed_port="$(allocate_port)"

  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${closed_port}"

  [ "$status" -eq 1 ]
  [[ "${lines[0]}" =~ '"status":"closed"' ]]
  [[ "${lines[0]}" =~ '"error":' ]]
}

# Regression: l4_probe must fail gracefully with usage on missing args
@test "l4_probe shows usage and exits 2 when called without arguments" {
  run "${BATS_CWD}/scripts/l4_probe.sh"

  [ "$status" -eq 2 ]
  [[ "$output" =~ "Usage:" ]]
}

# Regression: l4_probe must reject invalid port numbers
@test "l4_probe exits 2 for invalid port number" {
  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "not_a_port"

  [ "$status" -eq 2 ]
  [[ "$output" =~ "Invalid port" ]]
}

# Regression: l4_probe must handle empty port list after trimming
@test "l4_probe exits 2 for empty port after whitespace trimming" {
  run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "  ,  "

  [ "$status" -eq 2 ]
}

# Regression: L4_PROBE_TIMEOUT environment variable must be respected
@test "l4_probe respects L4_PROBE_TIMEOUT environment variable" {
  # Use a very short timeout so the test doesn't hang
  closed_port="$(allocate_port)"

  L4_PROBE_TIMEOUT=1 run "${BATS_CWD}/scripts/l4_probe.sh" 127.0.0.1 "${closed_port}"

  [ "$status" -eq 1 ]
  # Should complete quickly with the short timeout
  [[ "${lines[0]}" =~ '"status":"closed"' ]]
}
