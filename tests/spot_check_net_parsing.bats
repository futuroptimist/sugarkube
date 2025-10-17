#!/usr/bin/env bats

setup() {
  export SKIP_SPOT_CHECK_MAIN=1
  TEST_BIN_DIR="$(mktemp -d)"
  PATH="${TEST_BIN_DIR}:$PATH"
  export PATH TEST_BIN_DIR
  cat <<'STUB' > "${TEST_BIN_DIR}/ping"
#!/usr/bin/env bash
if [[ -n "${PING_FIXTURE:-}" ]]; then
  cat "${PING_FIXTURE}"
fi
exit "${PING_EXIT_CODE:-0}"
STUB
  chmod +x "${TEST_BIN_DIR}/ping"
  # shellcheck disable=SC1091
  source "$BATS_TEST_DIRNAME/../scripts/spot_check.sh"
  LOG_DIR="${BATS_TEST_TMPDIR}"
  LOG_FILE="${LOG_DIR}/spot-check.log"
  export LOG_DIR LOG_FILE
  mkdir -p "${LOG_DIR}"
}

teardown() {
  if [[ -d "${TEST_BIN_DIR:-}" ]]; then
    rm -rf "${TEST_BIN_DIR}"
  fi
  unset PING_FIXTURE PING_EXIT_CODE
  unset SKIP_SPOT_CHECK_MAIN
}

@test "LAN ping parsing extracts zero loss and low latency" {
  PING_FIXTURE="${BATS_TEST_TMPDIR}/lan.out"
  export PING_FIXTURE
  cat <<'LAN' > "${PING_FIXTURE}"
PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.

--- 192.168.1.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3004ms
rtt min/avg/max/mdev = 0.300/0.402/0.550/0.100 ms
LAN
  IFS=' ' read -r loss avg < <(_parse_ping_summary "192.168.1.1" "LAN")
  [ "$loss" = "0" ]
  [ "$avg" = "0.402" ]
}

@test "WAN ping parsing handles typical internet RTT" {
  PING_FIXTURE="${BATS_TEST_TMPDIR}/wan.out"
  export PING_FIXTURE
  cat <<'WAN' > "${PING_FIXTURE}"
PING 1.1.1.1 (1.1.1.1) 56(84) bytes of data.

--- 1.1.1.1 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 4005ms
rtt min/avg/max/mdev = 4.950/5.512/5.890/0.210 ms
WAN
  IFS=' ' read -r loss avg < <(_parse_ping_summary "1.1.1.1" "WAN")
  [ "$loss" = "0" ]
  [ "$avg" = "5.512" ]
}

@test "Parser tolerates localized packet summary text" {
  PING_FIXTURE="${BATS_TEST_TMPDIR}/locale.out"
  export PING_FIXTURE
  cat <<'LOC' > "${PING_FIXTURE}"
PING router (192.168.0.1) 56(84) bytes of data.

--- router ping statistics ---
4 paquetes transmitidos, 3 recibidos, 25% paquetes perdidos, tiempo 3000ms
rtt min/avg/max/mdev = 0.700/1.234/2.000/0.400 ms
LOC
  IFS=' ' read -r loss avg < <(_parse_ping_summary "router" "LAN-es")
  [ "$loss" = "100" ]
  [ "$avg" = "1.234" ]
}

@test "Parser returns defaults when RTT line missing" {
  PING_FIXTURE="${BATS_TEST_TMPDIR}/error.out"
  export PING_FIXTURE
  cat <<'ERR' > "${PING_FIXTURE}"
ping: unknown host example.invalid
ERR
  IFS=' ' read -r loss avg < <(_parse_ping_summary "example.invalid" "WAN-error")
  [ "$loss" = "100" ]
  [ "$avg" = "9999" ]
}
