#!/usr/bin/env bats

setup() {
  TMP_DIR=$(mktemp -d)
  STUB_BIN="${TMP_DIR}/bin"
  mkdir -p "${STUB_BIN}"

  cat <<'STUB' > "${STUB_BIN}/ping"
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ -z "${PING_FIXTURE:-}" ]]; then
  echo "PING_FIXTURE not set" >&2
  exit 1
fi
cat "${PING_FIXTURE}"
exit "${PING_EXIT_CODE:-0}"
STUB
  chmod +x "${STUB_BIN}/ping"

  LOG_FILE_PATH="${TMP_DIR}/log"
  touch "${LOG_FILE_PATH}"
  SCRIPT_PATH="${BATS_TEST_DIRNAME}/../scripts/spot_check.sh"
  ORIG_PATH="${PATH}"
  PATH="${STUB_BIN}:${PATH}"
}

teardown() {
  PATH="${ORIG_PATH}"
  rm -rf "${TMP_DIR}"
}

run_parser() {
  local fixture="$1"
  local label="$2"
  run env PATH="${PATH}" \
    LOG_FILE="${LOG_FILE_PATH}" \
    SPOT_CHECK_LIB_ONLY=1 \
    PING_FIXTURE="${fixture}" \
    bash -c 'source "$1"; _parse_ping_summary "example.com" "$2"' _ "${SCRIPT_PATH}" "${label}"
}

@test "_parse_ping_summary handles low-latency LAN output" {
  local fixture="${TMP_DIR}/lan.out"
  cat <<'EOF_FIX' > "${fixture}"
PING 192.168.86.1 (192.168.86.1) 56(84) bytes of data.

--- 192.168.86.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3003ms
rtt min/avg/max/mdev = 0.374/0.402/0.453/0.033 ms
EOF_FIX

  run_parser "${fixture}" "LAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 0.402" ]
}

@test "_parse_ping_summary handles WAN latency" {
  local fixture="${TMP_DIR}/wan.out"
  cat <<'EOF_FIX' > "${fixture}"
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 4005ms
rtt min/avg/max/mdev = 5.278/5.512/5.844/0.205 ms
EOF_FIX

  run_parser "${fixture}" "WAN"
  [ "$status" -eq 0 ]
  [ "$output" = "0 5.512" ]
}

@test "_parse_ping_summary falls back on 100% loss" {
  local fixture="${TMP_DIR}/loss.out"
  cat <<'EOF_FIX' > "${fixture}"
PING 192.168.86.1 (192.168.86.1) 56(84) bytes of data.

--- 192.168.86.1 ping statistics ---
4 packets transmitted, 0 received, 100% packet loss, time 4005ms
EOF_FIX

  run_parser "${fixture}" "LAN"
  [ "$status" -eq 0 ]
  [ "$output" = "100 9999" ]
}

@test "_parse_ping_summary tolerates localized packet summary" {
  local fixture="${TMP_DIR}/locale.out"
  cat <<'EOF_FIX' > "${fixture}"
PING example.net (203.0.113.5) 56(84) bytes of data.

--- example.net ping statistics ---
4 paquets transmis, 4 reçus, 0% paquets perdus, temps 3012ms
rtt min/avg/max/mdev = 12.114/12.345/12.612/0.207 ms
EOF_FIX

  run_parser "${fixture}" "WAN"
  [ "$status" -eq 0 ]
  [ "$output" = "100 12.345" ]
}
