#!/usr/bin/env bats
# Test wait_for_avahi_dbus.sh CLI fallback behavior

setup() {
  # Create temp directory for test environment
  TEST_TMP_DIR="$BATS_TEST_TMPDIR"
  BIN_DIR="${TEST_TMP_DIR}/bin"
  mkdir -p "${BIN_DIR}"
  
  # Save original PATH and add our bin dir
  ORIG_PATH="${PATH}"
  export PATH="${BIN_DIR}:${PATH}"
  
  # Script under test
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/.." && pwd)"
  WAIT_DBUS_SCRIPT="${REPO_ROOT}/scripts/wait_for_avahi_dbus.sh"
}

teardown() {
  # Restore PATH
  export PATH="${ORIG_PATH}"
}

# Helper to create a fake systemctl that reports avahi-daemon as active
create_systemctl_stub() {
  cat >"${BIN_DIR}/systemctl" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  is-active)
    echo "active"
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
EOF
  chmod +x "${BIN_DIR}/systemctl"
}

# Helper to create a fake busctl that always fails (simulating D-Bus unavailable)
create_busctl_stub_failing() {
  cat >"${BIN_DIR}/busctl" <<'EOF'
#!/usr/bin/env bash
echo "Call failed: Method GetVersionString with signature on interface org.freedesktop.Avahi.Server doesn't exist" >&2
exit 1
EOF
  chmod +x "${BIN_DIR}/busctl"
}

# Helper to create a working avahi-browse stub
create_avahi_browse_stub_working() {
  cat >"${BIN_DIR}/avahi-browse" <<'EOF'
#!/usr/bin/env bash
# Simulate successful avahi-browse
echo "+;eth0;IPv4;test;_test._tcp;local"
exit 0
EOF
  chmod +x "${BIN_DIR}/avahi-browse"
}

# Helper to create a failing avahi-browse stub
create_avahi_browse_stub_failing() {
  cat >"${BIN_DIR}/avahi-browse" <<'EOF'
#!/usr/bin/env bash
# Simulate avahi-browse failure
echo "Avahi daemon not running" >&2
exit 2
EOF
  chmod +x "${BIN_DIR}/avahi-browse"
}

@test "wait_for_avahi_dbus exits 2 (skip) when D-Bus fails but avahi-browse works" {
  create_systemctl_stub
  create_busctl_stub_failing
  create_avahi_browse_stub_working
  
  # Set short timeout so test runs fast
  export AVAHI_DBUS_WAIT_MS=100
  
  run bash "${WAIT_DBUS_SCRIPT}"
  
  # Should exit with status 2 (skip/disabled)
  [ "$status" -eq 2 ]
  
  # Should log the CLI fallback
  printf '%s\n' "$output" | grep -q "cli_fallback=ok"
  printf '%s\n' "$output" | grep -q "reason=dbus_unavailable_cli_ok"
  printf '%s\n' "$output" | grep -q "outcome=skip"
}

@test "wait_for_avahi_dbus exits 1 (error) when both D-Bus and avahi-browse fail" {
  create_systemctl_stub
  create_busctl_stub_failing
  create_avahi_browse_stub_failing
  
  # Set short timeout
  export AVAHI_DBUS_WAIT_MS=100
  
  run bash "${WAIT_DBUS_SCRIPT}"
  
  # Should exit with status 1 (error)
  [ "$status" -eq 1 ]
  
  # Should log timeout
  printf '%s\n' "$output" | grep -q "outcome=timeout"
}

@test "wait_for_avahi_dbus accepts avahi-browse exit code 1 (no results) as success" {
  create_systemctl_stub
  create_busctl_stub_failing
  
  # avahi-browse exits 1 when no services found (this is still considered functional)
  cat >"${BIN_DIR}/avahi-browse" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "${BIN_DIR}/avahi-browse"
  
  export AVAHI_DBUS_WAIT_MS=100
  
  run bash "${WAIT_DBUS_SCRIPT}"
  
  # Should exit with status 2 (skip) since exit 1 is acceptable
  [ "$status" -eq 2 ]
  printf '%s\n' "$output" | grep -q "cli_fallback=ok"
}

@test "wait_for_avahi_dbus logs D-Bus error details before falling back" {
  create_systemctl_stub
  create_busctl_stub_failing
  create_avahi_browse_stub_working
  
  export AVAHI_DBUS_WAIT_MS=100
  
  run bash "${WAIT_DBUS_SCRIPT}"
  
  [ "$status" -eq 2 ]
  
  # Should include D-Bus error in logs
  printf '%s\n' "$output" | grep -q "bus_status"
  printf '%s\n' "$output" | grep -q "bus_error"
}

@test "wait_for_avahi_dbus skips CLI fallback when avahi-browse not available" {
  create_systemctl_stub
  create_busctl_stub_failing
  
  # No avahi-browse available
  
  export AVAHI_DBUS_WAIT_MS=100
  
  run bash "${WAIT_DBUS_SCRIPT}"
  
  # Should exit with error since no fallback possible
  [ "$status" -eq 1 ]
  printf '%s\n' "$output" | grep -q "outcome=timeout"
}
