#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
  export TEST_ROOT="${BATS_TEST_TMPDIR}/wipe_test"
  mkdir -p "${TEST_ROOT}"
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

create_systemctl_stub() {
  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
# Stub systemctl - just log what was called
echo "systemctl $*" >> "${BATS_TEST_TMPDIR}/systemctl.log"
exit 0
EOS
}

@test "wipe_node.sh removes all k3s token files" {
  create_systemctl_stub
  
  # Create mock token files
  local k3s_dir="${TEST_ROOT}/var/lib/rancher/k3s"
  local server_dir="${k3s_dir}/server"
  local boot_dir="${TEST_ROOT}/boot"
  
  mkdir -p "${server_dir}" "${boot_dir}"
  echo "mock-server-token" > "${server_dir}/token"
  echo "mock-node-token" > "${server_dir}/node-token"
  echo "NODE_TOKEN=mock-boot-token" > "${boot_dir}/sugarkube-node-token"
  
  # Create avahi files
  local avahi_dir="${TEST_ROOT}/etc/avahi"
  mkdir -p "${avahi_dir}/services"
  echo "mock avahi service" > "${avahi_dir}/services/k3s-sugar-dev.service"
  echo "192.168.1.100 sugarkube0-tyyk.local" > "${avahi_dir}/hosts"
  
  # Create stubs for uninstallers (not found on PATH)
  stub_command k3s-killall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  stub_command k3s-uninstall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  stub_command k3s-agent-uninstall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  
  # Run wipe_node.sh with mocked paths
  run env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_K3S_SERVER_TOKEN_PATH="${server_dir}/token" \
    SUGARKUBE_NODE_TOKEN_PATH="${server_dir}/node-token" \
    SUGARKUBE_BOOT_TOKEN_PATH="${boot_dir}/sugarkube-node-token" \
    SUGARKUBE_K3S_DATA_DIR="${k3s_dir}" \
    SUGARKUBE_AVAHI_HOSTS_PATH="${avahi_dir}/hosts" \
    SUGARKUBE_RUNTIME_DIR="${TEST_ROOT}/run/sugarkube" \
    bash "${BATS_CWD}/scripts/wipe_node.sh"
  
  [ "$status" -eq 0 ]
  
  # Verify all token files were removed
  [ ! -f "${server_dir}/token" ]
  [ ! -f "${server_dir}/node-token" ]
  [ ! -f "${boot_dir}/sugarkube-node-token" ]
  [ ! -d "${k3s_dir}" ]
  
  # Verify avahi hosts file was removed
  [ ! -f "${avahi_dir}/hosts" ]
  
  # Verify output mentions the cleanup
  [[ "${output}" =~ "removed" ]] || [[ "${output}" =~ "Summary" ]]
}

@test "wipe_node.sh handles missing token files gracefully" {
  create_systemctl_stub
  
  # Create minimal directory structure but no token files
  local k3s_dir="${TEST_ROOT}/var/lib/rancher/k3s"
  mkdir -p "${k3s_dir}"
  
  stub_command k3s-killall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  stub_command k3s-uninstall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  stub_command k3s-agent-uninstall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  
  run env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_K3S_DATA_DIR="${k3s_dir}" \
    SUGARKUBE_RUNTIME_DIR="${TEST_ROOT}/run/sugarkube" \
    bash "${BATS_CWD}/scripts/wipe_node.sh"
  
  [ "$status" -eq 0 ]
  [[ "${output}" =~ "Completed wipe" ]]
}

@test "wipe_node.sh removes avahi hosts file to prevent stale hostname mappings" {
  create_systemctl_stub
  
  local avahi_dir="${TEST_ROOT}/etc/avahi"
  mkdir -p "${avahi_dir}"
  
  # Create a hosts file with a stale hostname mapping (like sugarkube0-tyyk.local)
  cat > "${avahi_dir}/hosts" <<EOF
192.168.1.100 sugarkube0-tyyk.local
192.168.1.101 sugarkube1-abcd.local
EOF
  
  stub_command k3s-killall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  stub_command k3s-uninstall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  stub_command k3s-agent-uninstall.sh <<'EOS'
#!/usr/bin/env bash
exit 0
EOS
  
  run env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_AVAHI_HOSTS_PATH="${avahi_dir}/hosts" \
    SUGARKUBE_RUNTIME_DIR="${TEST_ROOT}/run/sugarkube" \
    bash "${BATS_CWD}/scripts/wipe_node.sh"
  
  [ "$status" -eq 0 ]
  
  # Verify the avahi hosts file was removed
  [ ! -f "${avahi_dir}/hosts" ]
  
  # Verify output mentions removal of hosts file
  [[ "${output}" =~ "removed:${avahi_dir}/hosts" ]] || [[ "${output}" =~ "Summary" ]]
}
