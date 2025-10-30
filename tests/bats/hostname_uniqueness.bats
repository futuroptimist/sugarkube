#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
}

create_hostname_stub() {
  stub_command hostname <<'EOS'
#!/usr/bin/env bash
if [ "$#" -eq 0 ]; then
  echo "sugarkube0"
  exit 0
fi
if [ "$1" = "-s" ]; then
  echo "sugarkube0"
  exit 0
fi
if [ "$1" = "-f" ]; then
  echo "sugarkube0.local"
  exit 0
fi
printf '%s\n' "$1" >>"${BATS_TEST_TMPDIR}/hostname_set"
exit 0
EOS
}

create_systemctl_stub() {
  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "is-active" ] && [ "$2" = "avahi-daemon" ]; then
  echo "active"
  exit 0
fi
exit 0
EOS
}

create_kubectl_stub() {
  stub_command kubectl <<'EOS'
#!/usr/bin/env bash
exit 1
EOS
  stub_command k3s <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "kubectl" ]; then
  exit 1
fi
exit 0
EOS
}

@test "appends suffix when mDNS collision detected" {
  create_hostname_stub
  create_systemctl_stub
  create_kubectl_stub

  local host_file="${BATS_TEST_TMPDIR}/hostname"
  printf '%s\n' "sugarkube0" >"${host_file}"

  run env \
    ENSURE_HOSTNAMECTL_BIN= \
    ENSURE_HOSTNAME_FILE="${host_file}" \
    ENSURE_UNIQUE_HOSTNAME_MDNS_HOSTS=$'sugarkube0.local\nsugarkube1.local' \
    "${BATS_CWD}/scripts/ensure_unique_hostname.sh"

  [ "$status" -eq 0 ]
  local updated
  updated="$(<"${host_file}")"
  [[ "${updated}" =~ ^sugarkube0-[a-z0-9]{4}$ ]]
  [[ -f "${BATS_TEST_TMPDIR}/hostname_set" ]]
  local invocation
  invocation="$(<"${BATS_TEST_TMPDIR}/hostname_set")"
  [[ "${invocation}" =~ ^sugarkube0-[a-z0-9]{4}$ ]]
}

@test "enables with-node-id drop-ins when hostname update fails" {
  create_hostname_stub
  create_systemctl_stub
  create_kubectl_stub

  local systemd_dir="${BATS_TEST_TMPDIR}/systemd"
  mkdir -p "${systemd_dir}"

  run env \
    ENSURE_HOSTNAMECTL_BIN="${BATS_TEST_TMPDIR}/missing-hostnamectl" \
    ENSURE_HOSTNAME_FILE="/dev/full" \
    ENSURE_SYSTEMD_DIR="${systemd_dir}" \
    ENSURE_UNIQUE_HOSTNAME_MDNS_HOSTS=$'sugarkube0.local' \
    "${BATS_CWD}/scripts/ensure_unique_hostname.sh"

  [ "$status" -eq 0 ]

  local server_dropin="${systemd_dir}/k3s.service.d/20-node-id.conf"
  local agent_dropin="${systemd_dir}/k3s-agent.service.d/20-node-id.conf"
  [ -f "${server_dropin}" ]
  [ -f "${agent_dropin}" ]
  grep -q 'Environment=K3S_WITH_NODE_ID=true' "${server_dropin}"
  grep -q 'Environment=K3S_WITH_NODE_ID=true' "${agent_dropin}"
}
