#!/usr/bin/env bats

parse_sample() {
  local sample="$1" host="$2" label="$3" exit_code="${4:-0}"
  local script="$BATS_TEST_DIRNAME/../scripts/spot_check.sh"
  local sample_file
  sample_file="$(mktemp)"
  printf '%s\n' "$sample" >"$sample_file"

  run bash -c "set -Eeuo pipefail
sample_file=\"\$1\"
host=\"\$2\"
label=\"\$3\"
script=\"\$4\"
exit_code=\"\$5\"
tmp=\$(mktemp -d)
cat <<'EOS' >\"\$tmp/ping\"
#!/usr/bin/env bash
cat \"\${PING_SAMPLE_FILE}\"
status=\"\${PING_SAMPLE_STATUS:-0}\"
exit \"\$status\"
EOS
chmod +x \"\$tmp/ping\"
export PATH=\"\$tmp:\$PATH\"
export PING_SAMPLE_FILE=\"\$sample_file\"
export PING_SAMPLE_STATUS=\"\$exit_code\"
export LOG_FILE=\$(mktemp)
export ARTIFACT_DIR=\$(mktemp -d)
export SPOT_CHECK_IMPORT=1
export RESULT_DATA=()
export PASSED=0 FAILED=0 WARNED=0 INFO=0 REQUIRED_FAILURES=0
export START_TIME=\"\$(date --iso-8601=seconds)\"
# shellcheck disable=SC1090
source \"\$script\"
result=\$(_parse_ping_summary \"\$host\" \"\$label\")
printf '%s\\n' \"\$result\"
rm -f \"\$LOG_FILE\" || true
rm -rf \"\$ARTIFACT_DIR\" \"\$tmp\" || true
" _ "$sample_file" "$host" "$label" "$script" "$exit_code"

  rm -f "$sample_file"
}

@test "LAN parser captures zero loss low latency" {
  parse_sample "PING 192.168.86.1 (192.168.86.1) 56(84) bytes of data.\n\n--- 192.168.86.1 ping statistics ---\n4 packets transmitted, 4 received, 0% packet loss, time 3006ms\nrtt min/avg/max/mdev = 0.352/0.402/0.487/0.045 ms" \
    "192.168.86.1" "LAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 0.402" ]
}

@test "WAN parser captures zero loss moderate latency" {
  parse_sample "PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.\n\n--- 1.1.1.1 ping statistics ---\n4 packets transmitted, 4 received, 0% packet loss, time 4005ms\nrtt min/avg/max/mdev = 5.102/5.532/6.004/0.310 ms" \
    "1.1.1.1" "WAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 5.532" ]
}

@test "Parser falls back to defaults on unreachable host" {
  parse_sample "PING 203.0.113.1 (203.0.113.1) 56(84) bytes of data.\nping: sendmsg: Network is unreachable" \
    "203.0.113.1" "WAN" 1
  [ "$status" -eq 0 ]
  [ "$output" = "100 9999" ]
}

@test "Parser tolerates localized summary wording" {
  parse_sample "PING example.com (93.184.216.34) 56(84) bytes of data.\n\n--- example.com ping statistics ---\n4 packets transmitted, 4 packets received, 0.0% packet loss, time 4004ms\nround-trip min/avg/max/stddev = 20.101/21.554/24.221/1.491 ms" \
    "example.com" "WAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0.0 21.554" ]
}
