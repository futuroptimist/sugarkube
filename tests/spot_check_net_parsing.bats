#!/usr/bin/env bats

setup() {
  export TEST_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "${TEST_BIN}"
  export PATH="${TEST_BIN}:$PATH"

  cat >"${TEST_BIN}/ping" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
cat "${PING_FIXTURE}"
STUB
  chmod +x "${TEST_BIN}/ping"

  export ARTIFACT_DIR="$BATS_TEST_TMPDIR/artifacts"
  export LOG_DIR="$BATS_TEST_TMPDIR/logs"
  export LOG_FILE="$LOG_DIR/spot-check.log"
  export JSON_FILE="$ARTIFACT_DIR/summary.json"
  export MD_FILE="$ARTIFACT_DIR/summary.md"
  export SPOT_CHECK_ALLOW_NON_ROOT=1
  mkdir -p "${LOG_DIR}" "${ARTIFACT_DIR}"
}

_run_parser() {
  local fixture="$1" host="$2" label="$3"
  local script_path="$BATS_TEST_DIRNAME/../scripts/spot_check.sh"
  export PING_FIXTURE="$fixture"
  run bash -c '
    set -Eeuo pipefail
    source "$1"
    result=$(_parse_ping_summary "$2" "$3")
    printf "%s\n" "$result"
  ' _ "$script_path" "$host" "$label"
}

_run_check() {
  local fixture="$1" label="$2" host="$3" max_avg="$4"
  local script_path="$BATS_TEST_DIRNAME/../scripts/spot_check.sh"
  export PING_FIXTURE="$fixture"
  run bash -c '
    set -Eeuo pipefail
    source "$1"
    result=$(check_ping_target "$2" "$3" "$4" true)
    printf "%s\n" "$result"
  ' _ "$script_path" "$label" "$host" "$max_avg"
}

@test "LAN parser extracts zero loss and sub-ms avg" {
  local fixture="$BATS_TEST_TMPDIR/lan.out"
  cat >"$fixture" <<'EOF_FIX'
PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.

--- 192.168.1.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3005ms
rtt min/avg/max/mdev = 0.301/0.402/0.512/0.045 ms
EOF_FIX
  _run_parser "$fixture" "192.168.1.1" "LAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 0.402" ]

  _run_check "$fixture" "LAN" "192.168.1.1" "10"
  [ "$status" -eq 0 ]
  [ "$output" = "ok|LAN loss=0%; avg=0.402ms" ]
}

@test "WAN parser extracts expected averages" {
  local fixture="$BATS_TEST_TMPDIR/wan.out"
  cat >"$fixture" <<'EOF_FIX'
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 4.901/5.512/6.103/0.221 ms
EOF_FIX
  _run_parser "$fixture" "1.1.1.1" "WAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 5.512" ]

  _run_check "$fixture" "WAN" "1.1.1.1" "100"
  [ "$status" -eq 0 ]
  [ "$output" = "ok|WAN loss=0%; avg=5.512ms" ]
}

@test "Parser tolerates 100 percent loss" {
  local fixture="$BATS_TEST_TMPDIR/loss.out"
  cat >"$fixture" <<'EOF_FIX'
PING host (10.0.0.1) 56(84) bytes of data.

--- host ping statistics ---
4 packets transmitted, 0 received, 100% packet loss, time 3002ms
EOF_FIX
  _run_parser "$fixture" "10.0.0.1" "LAN"
  [ "$status" -eq 0 ]
  [ "$output" = "100 9999" ]
}

@test "Parser normalizes locale decimal commas" {
  local fixture="$BATS_TEST_TMPDIR/locale.out"
  cat >"$fixture" <<'EOF_FIX'
PING exemplo.com (203.0.113.5) 56(84) bytes of data.

--- exemplo.com ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 4010ms
rtt min/avg/max/mdev = 4,201/5,014/6,822/0,401 ms
EOF_FIX
  _run_parser "$fixture" "exemplo.com" "WAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 5.014" ]
}
