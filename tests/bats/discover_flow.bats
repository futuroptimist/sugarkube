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
if [ "$1" = "is-active" ] && [ "$2" = "avahi-daemon" ]; then
  echo "active"
  exit 0
fi
exit 0
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

if [ "$1" != "-rtp" ]; then
  echo "unexpected avahi-browse invocation: $*" >&2
  exit 1
fi

service_type="$2"
service_file="${SUGARKUBE_AVAHI_SERVICE_FILE:-${SUGARKUBE_AVAHI_SERVICE_DIR:-/etc/avahi/services}/k3s-${SUGARKUBE_CLUSTER:-sugar}-${SUGARKUBE_ENV:-dev}.service}"

if [ ! -f "${service_file}" ]; then
  exit 1
fi

python3 - "$service_file" "$service_type" <<'PY'
import os
import sys
import xml.etree.ElementTree as ET

path, expected_type = sys.argv[1:3]
tree = ET.parse(path)
root = tree.getroot()

service = root.find("./service")
if service is None:
    service = root.find(".//service")
if service is None:
    sys.exit(1)

service_type = service.findtext("type") or ""
if expected_type and expected_type != service_type:
    sys.exit(1)

name = root.findtext("./name") or ""
port = service.findtext("port") or ""
records = [node.text or "" for node in service.findall("txt-record")]

host = os.environ.get("HOSTNAME", "stub-host") + ".local"

parts = [
    "=;eth0;IPv4",
    name,
    service_type,
    "local",
    host,
    "127.0.0.1",
    port,
]
parts.extend(f"txt={record}" for record in records)

print(";".join(parts))
PY
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

create_api_ready_stub() {
  local target="$BATS_TEST_TMPDIR/api-ready-check.sh"
  cat <<'EOS' >"${target}"
#!/usr/bin/env bash
set -euo pipefail
if [ -n "${SERVER_HOST:-}" ]; then
  printf 'ts=stub level=info event=apiready outcome=ok host="%s"\n' "${SERVER_HOST}" >&2
else
  printf 'ts=stub level=info event=apiready outcome=ok\n' >&2
fi
exit 0
EOS
  chmod +x "${target}"
  echo "${target}"
}

@test "wait_for_avahi_dbus reports ready when Avahi registers quickly" {
  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "is-active" ] && [ "$2" = "avahi-daemon" ]; then
  echo "active"
  exit 0
fi
echo "unexpected systemctl invocation: $*" >&2
exit 1
EOS

  stub_command busctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "--system" ]; then
  shift
fi
if [ "$1" = "--timeout=2" ]; then
  shift
fi
if [ "$1" = "call" ] && [ "$2" = "org.freedesktop.Avahi" ]; then
  echo 's "stub"'
  exit 0
fi
echo "unexpected busctl call: $*" >&2
exit 1
EOS

  run env \
    AVAHI_DBUS_WAIT_MS=200 \
    "${BATS_CWD}/scripts/wait_for_avahi_dbus.sh"

  [ "$status" -eq 0 ]
  [[ "$output" == *"event=avahi_dbus_ready outcome=ok"* ]]
  [[ "$output" == *"systemd_state=active"* ]]
  [[ "$output" == *"bus_status=ok"* ]]
}

@test "wait_for_avahi_dbus exits with disabled when enable-dbus=no" {
  conf_path="${BATS_TEST_TMPDIR}/avahi-disabled.conf"
  cat <<'CONF' >"${conf_path}"
[server]
enable-dbus=no
CONF

  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "is-active" ] && [ "$2" = "avahi-daemon" ]; then
  echo "active"
  exit 0
fi
exit 0
EOS

  run env \
    AVAHI_CONF_PATH="${conf_path}" \
    AVAHI_DBUS_WAIT_MS=200 \
    "${BATS_CWD}/scripts/wait_for_avahi_dbus.sh"

  [ "$status" -eq 2 ]
  [[ "$output" == *"event=avahi_dbus_ready outcome=disabled"* ]]
  [[ "$output" == *"severity=info"* ]]
}

@test "wait_for_avahi_dbus logs timeout details when Avahi is absent" {
  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "is-active" ] && [ "$2" = "avahi-daemon" ]; then
  echo "active"
  exit 0
fi
echo "unexpected systemctl invocation: $*" >&2
exit 1
EOS

  stub_command busctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "--system" ]; then
  shift
fi
if [ "$1" = "--timeout=2" ]; then
  shift
fi
if [ "$1" = "call" ] && [ "$2" = "org.freedesktop.Avahi" ]; then
  echo "Failed to call method: org.freedesktop.DBus.Error.NameHasNoOwner: Name not owned" >&2
  exit 1
fi
echo "unexpected busctl call: $*" >&2
exit 1
EOS

  run env \
    AVAHI_DBUS_WAIT_MS=200 \
    "${BATS_CWD}/scripts/wait_for_avahi_dbus.sh"

  [ "$status" -eq 1 ]
  [[ "$output" == *"event=avahi_dbus_ready outcome=timeout"* ]]
  [[ "$output" == *"systemd_state=active"* ]]
  [[ "$output" == *"bus_status=name_not_owned"* ]]
  [[ "$output" == *"bus_error=org.freedesktop.DBus.Error.NameHasNoOwner"* ]]
}

@test "discover flow waits for Avahi liveness after reload" {
  stub_common_network_tools

  stub_command gdbus <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "introspect" ]; then
  exit 0
fi
exit 0
EOS

  stub_command busctl <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "--system" ]; then
  shift
fi
if [ "$1" = "--timeout=2" ]; then
  shift
fi
if [ "$1" = "call" ] && [ "$2" = "org.freedesktop.Avahi" ]; then
  echo 's "stub"'
  exit 0
fi
if [ "$1" = "list" ]; then
  echo "org.freedesktop.Avahi 100 200"
  exit 0
fi
echo "unexpected busctl call: $*" >&2
exit 1
EOS

  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
echo "$*" >>"${BATS_TEST_TMPDIR}/systemctl.log"
if [ "$1" = "is-active" ] && [ "$2" = "avahi-daemon" ]; then
  echo "active"
  exit 0
fi
exit 0
EOS

  stub_command sleep <<'EOS'
#!/usr/bin/env bash
echo "$*" >>"${BATS_TEST_TMPDIR}/sleep.log"
exit 0
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
log="${BATS_TEST_TMPDIR}/avahi-browse.log"
printf '%s\n' "$*" >>"${log}"
ready_flag="${BATS_TEST_TMPDIR}/avahi_all_ready"
count_file="${BATS_TEST_TMPDIR}/avahi_all_count"
case "$1" in
  --all)
    count=0
    if [ -f "${count_file}" ]; then
      count="$(cat "${count_file}")"
    fi
    count=$((count + 1))
    printf '%s' "${count}" >"${count_file}"
    if [ "${count}" -eq 1 ]; then
      exit 0
    fi
    printf '%s\n' "=;eth0;IPv4;ready;_k3s-demo-test._tcp;local;ready.local;192.0.2.1;1234;"
    printf '%s' 1 >"${ready_flag}"
    exit 0
    ;;
  -rtp)
    if [ ! -f "${ready_flag}" ]; then
      echo "liveness_not_confirmed" >&2
      exit 1
    fi
    printf '%s\n' "=;eth0;IPv4;k3s-demo-test@demo.local (bootstrap);_k3s-demo-test._tcp;local;demo.local;192.0.2.10;6443;"
    exit 0
    ;;
esac
echo "unexpected avahi-browse invocation: $*" >&2
exit 1
EOS

  avahi_conf="${BATS_TEST_TMPDIR}/avahi.conf"
  cat <<'CONF' >"${avahi_conf}"
[server]
CONF

  mkdir -p "${BATS_TEST_TMPDIR}/avahi/services"
  mkdir -p "${BATS_TEST_TMPDIR}/run"
  mkdir -p "${BATS_TEST_TMPDIR}/mdns"

  mdns_stub="$(create_mdns_stub 0)"

  run env \
    ALLOW_NON_ROOT=1 \
    AVAHI_CONF_PATH="${avahi_conf}" \
    SUGARKUBE_CLUSTER=demo \
    SUGARKUBE_ENV=test \
    SUGARKUBE_AVAHI_SERVICE_DIR="${BATS_TEST_TMPDIR}/avahi/services" \
    SUGARKUBE_MDNS_RUNTIME_DIR="${BATS_TEST_TMPDIR}/mdns" \
    SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    SUGARKUBE_MDNS_PUBLISH_ADDR=192.0.2.10 \
    SUGARKUBE_MDNS_SELF_CHECK_BIN="${mdns_stub}" \
    SUGARKUBE_MDNS_BOOT_RETRIES=1 \
    SUGARKUBE_MDNS_BOOT_DELAY=0 \
    "${BATS_CWD}/scripts/k3s-discover.sh" --test-bootstrap-publish

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=avahi_liveness outcome=ok ]]
  [[ "$output" =~ attempt=2 ]]

  [ -f "${BATS_TEST_TMPDIR}/avahi_all_count" ]
  [ "$(cat "${BATS_TEST_TMPDIR}/avahi_all_count")" -eq 2 ]
}

@test "discover flow joins existing server when discovery succeeds" {
  stub_common_network_tools
  create_curl_stub
  stub_command timeout <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  api_ready_stub="$(create_api_ready_stub)"

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
    SUGARKUBE_API_READY_CHECK_BIN="${api_ready_stub}" \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ phase=install_join ]]

  local service_file
  service_file="${BATS_TEST_TMPDIR}/avahi/services/k3s-sugar-dev.service"
  if [ -f "${service_file}" ]; then
    run avahi-browse -rtp _k3s-sugar-dev._tcp
    [ "$status" -eq 0 ]
    [[ "$output" =~ txt=cluster=sugar ]]
    [[ "$output" =~ txt=env=dev ]]
  fi
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

  api_ready_stub="$(create_api_ready_stub)"

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
    SUGARKUBE_API_READY_CHECK_BIN="${api_ready_stub}" \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=bootstrap_selfcheck_election ]] || false
  [[ "$output" =~ outcome=winner ]]
  [[ "$output" =~ phase=install_single ]]

  local service_file
  service_file="${BATS_TEST_TMPDIR}/avahi/services/k3s-sugar-dev.service"
  if [ -f "${service_file}" ]; then
    run avahi-browse -rtp _k3s-sugar-dev._tcp
    [ "$status" -eq 0 ]
    [[ "$output" =~ txt=role=bootstrap ]]
    [[ "$output" =~ txt=phase=bootstrap ]]
  fi
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

  api_ready_stub="$(create_api_ready_stub)"

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
    SUGARKUBE_API_READY_CHECK_BIN="${api_ready_stub}" \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -eq 124 ]
  [[ "$output" =~ outcome=follower ]]
}

@test "Avahi check warns on IPv4 suffix and can auto-fix" {
  conf_path="${BATS_TEST_TMPDIR}/avahi-daemon.conf"
  cat <<'CONF' >"${conf_path}"
[server]
allow-interfaces=eth0.IPv4
CONF

  run env AVAHI_CONF_PATH="${conf_path}" "${BATS_CWD}/scripts/check_avahi_config_effective.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"warning=allow_interfaces_suffix"* ]]
  [[ "$output" == *"allow_interfaces=eth0"* ]]
  run cat "${conf_path}"
  [[ "$output" == *"eth0.IPv4"* ]]

  run env AVAHI_CONF_PATH="${conf_path}" SUGARKUBE_FIX_AVAHI=1 "${BATS_CWD}/scripts/check_avahi_config_effective.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"warning=allow_interfaces_suffix"* ]]
  [[ "$output" == *"fix_applied=allow_interfaces_suffix"* ]]
  run cat "${conf_path}"
  [[ "$output" == *"allow-interfaces=eth0"* ]]
}
