#!/usr/bin/env bats

load helpers/path_stub

setup() {
  ORIGINAL_PATH="$PATH"
  unset _BATS_PATH_STUB_DIR
  PATH="$ORIGINAL_PATH"
  setup_path_stub_dir
}

teardown() {
  PATH="$ORIGINAL_PATH"
}

stub_common_network_tools() {
  stub_command ip <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-o" ] && [ "$2" = "link" ] && [ "$3" = "show" ] && [ "$4" = "up" ]; then
  echo "2: eth0: <UP>"
  exit 0
fi
if [ "$1" = "-4" ] && [ "$2" = "-o" ] && [ "$3" = "addr" ] && [ "$4" = "show" ]; then
  echo "2: eth0    inet 192.168.3.10/24"
  exit 0
fi
exit 0
EOS

  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  stub_command avahi-publish <<'EOS'
#!/usr/bin/env bash
sleep 60
EOS

  stub_command avahi-publish-address <<'EOS'
#!/usr/bin/env bash
sleep 60
EOS
}

create_configure_stub() {
  local target="$BATS_TEST_TMPDIR/configure-avahi-stub.sh"
  cat <<'EOS' > "$target"
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$target"
  echo "$target"
}

create_mdns_stub() {
  local status="$1"
  local target="$BATS_TEST_TMPDIR/mdns-selfcheck-${status}.sh"
  cat <<EOS > "$target"
#!/usr/bin/env bash
status=${status}
if [ "\$status" -eq 0 ]; then
  echo "host=\${SUGARKUBE_EXPECTED_HOST:-stub.local} attempts=1 ms_elapsed=5"
  exit 0
fi
exit "\$status"
EOS
  chmod +x "$target"
  echo "$target"
}

create_election_stub() {
  local winner="$1"
  local target="$BATS_TEST_TMPDIR/elect-${winner}.sh"
  cat <<EOS > "$target"
#!/usr/bin/env bash
echo "winner=${winner}"
echo "key=test-${winner}"
exit 0
EOS
  chmod +x "$target"
  echo "$target"
}

create_net_diag_stub() {
  local target="$BATS_TEST_TMPDIR/net-diag-stub.sh"
  cat <<'EOS' > "$target"
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "$target"
  echo "$target"
}

create_curl_stub() {
  stub_command curl <<'EOS'
#!/usr/bin/env bash
if [ -n "$BATS_TEST_TMPDIR" ]; then
  echo "curl $*" >> "$BATS_TEST_TMPDIR/curl.log"
fi
cat <<'SCRIPT'
exit 0
SCRIPT
EOS
}

@test "discover flow joins existing server when discovery succeeds" {
  stub_common_network_tools
  create_curl_stub
  stub_command timeout <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  configure_stub="$(create_configure_stub)"
  token_path="${BATS_TEST_TMPDIR}/node-token"
  printf %s\n "demo-token" > "$token_path"

  run env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_CONFIGURE_AVAHI_BIN="${configure_stub}" \
    SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    AVAHI_CONF_PATH="${BATS_TEST_TMPDIR}/avahi.conf" \
    SUGARKUBE_AVAHI_SERVICE_DIR="${BATS_TEST_TMPDIR}/avahi/services" \
    SUGARKUBE_MDNS_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    SUGARKUBE_MDNS_FIXTURE_FILE="${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt" \
    SUGARKUBE_MDNS_PUBLISH_ADDR=192.168.3.10 \
    SUGARKUBE_SERVERS=3 \
    SUGARKUBE_NODE_TOKEN_PATH="${token_path}" \
    SKIP_MDNS_SELF_CHECK=1 \
    DISCOVERY_WAIT_SECS=0 \
    ELECTION_HOLDOFF=0 \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ phase=install_join ]]
}

@test "discover flow elects winner after self-check failure" {
  stub_common_network_tools
  create_curl_stub
  stub_command timeout <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  configure_stub="$(create_configure_stub)"
  mdns_stub="$(create_mdns_stub 94)"
  election_stub="$(create_election_stub yes)"
  net_diag_stub="$(create_net_diag_stub)"
  token_path="${BATS_TEST_TMPDIR}/node-token"
  printf %s\n "demo-token" > "$token_path"

  run env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_CONFIGURE_AVAHI_BIN="${configure_stub}" \
    SUGARKUBE_MDNS_SELF_CHECK_BIN="${mdns_stub}" \
    SUGARKUBE_ELECT_LEADER_BIN="${election_stub}" \
    SUGARKUBE_NET_DIAG_BIN="${net_diag_stub}" \
    SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    AVAHI_CONF_PATH="${BATS_TEST_TMPDIR}/avahi.conf" \
    SUGARKUBE_AVAHI_SERVICE_DIR="${BATS_TEST_TMPDIR}/avahi/services" \
    SUGARKUBE_MDNS_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    SUGARKUBE_MDNS_FIXTURE_FILE="${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt" \
    SUGARKUBE_MDNS_PUBLISH_ADDR=192.168.3.10 \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_NODE_TOKEN_PATH="${token_path}" \
    SUGARKUBE_MDNS_BOOT_RETRIES=1 \
    SUGARKUBE_MDNS_BOOT_DELAY=0 \
    DISCOVERY_WAIT_SECS=0 \
    ELECTION_HOLDOFF=0 \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=bootstrap_selfcheck_election ]] || false
  [[ "$output" =~ outcome=winner ]]
  [[ "$output" =~ phase=install_single ]]
}

@test "discover flow remains follower after self-check failure" {
  stub_common_network_tools
  create_curl_stub

  configure_stub="$(create_configure_stub)"
  mdns_stub="$(create_mdns_stub 94)"
  election_stub="$(create_election_stub no)"
  net_diag_stub="$(create_net_diag_stub)"
  token_path="${BATS_TEST_TMPDIR}/node-token"
  printf %s\n "demo-token" > "$token_path"

  run timeout 1 env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_CONFIGURE_AVAHI_BIN="${configure_stub}" \
    SUGARKUBE_MDNS_SELF_CHECK_BIN="${mdns_stub}" \
    SUGARKUBE_ELECT_LEADER_BIN="${election_stub}" \
    SUGARKUBE_NET_DIAG_BIN="${net_diag_stub}" \
    SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    AVAHI_CONF_PATH="${BATS_TEST_TMPDIR}/avahi.conf" \
    SUGARKUBE_AVAHI_SERVICE_DIR="${BATS_TEST_TMPDIR}/avahi/services" \
    SUGARKUBE_MDNS_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    SUGARKUBE_MDNS_FIXTURE_FILE="${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt" \
    SUGARKUBE_MDNS_PUBLISH_ADDR=192.168.3.10 \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_NODE_TOKEN_PATH="${token_path}" \
    SUGARKUBE_MDNS_BOOT_RETRIES=1 \
    SUGARKUBE_MDNS_BOOT_DELAY=0 \
    DISCOVERY_WAIT_SECS=0 \
    ELECTION_HOLDOFF=0 \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -eq 124 ]
  [[ "$output" =~ outcome=follower ]]
}
