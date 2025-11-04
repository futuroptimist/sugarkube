#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
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

stub_avahi_browse_with_fixtures() {
  local main_fixture="$1"
  local services_fixture="$2"
  export \
    AVAHI_BROWSE_MAIN_FIXTURE="${main_fixture}" \
    AVAHI_BROWSE_SERVICES_FIXTURE="${services_fixture}"

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

main="${AVAHI_BROWSE_MAIN_FIXTURE:-}"
services="${AVAHI_BROWSE_SERVICES_FIXTURE:-}"

last=""
if [ "$#" -gt 0 ]; then
  last="${!#}"
fi

if [ "${last}" = "_services._dns-sd._udp" ]; then
  if [ -n "${services}" ] && [ -f "${services}" ]; then
    cat "${services}"
  fi
  exit 0
fi

if [ -n "${main}" ] && [ -f "${main}" ]; then
  cat "${main}"
fi
EOS
}

@test "mdns self-check succeeds when instance is discoverable" {
  stub_avahi_browse_with_fixtures \
    "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt" \
    "${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
if [ "$#" -ne 1 ]; then
  echo "unexpected arguments" >&2
  exit 1
fi
printf '%s %s\n' "$1" "192.168.3.10"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=2 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=100 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=100 \
    LOG_LEVEL=debug \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=mdns_selfcheck ]]
  [[ "$output" =~ host=sugarkube0.local ]]
  [[ "$output" =~ ipv4=192.168.3.10 ]]
  [[ "$output" =~ available_types.*_k3s-sugar-dev._tcp ]]
}

@test "mdns self-check confirms via CLI-only resolution" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
  exit 0
fi
cat <<'TXT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (agent);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt=cluster=sugar;txt=env=dev;txt=role=agent;txt=phase=agent
TXT
EOS

  stub_command avahi-resolve-host-name <<'EOS'
#!/usr/bin/env bash
target="$1"
shift || true
while [ "$#" -gt 0 ]; do
  case "$1" in
    -4)
      ;;
    --timeout=*)
      ;;
    *)
      echo "unexpected argument: $1" >&2
      exit 1
      ;;
  esac
  shift || true
done
printf '%s %s\n' "${target}" "10.0.0.5"
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "$*" >"${BATS_TEST_TMPDIR}/avahi-resolve-invoked"
exit 2
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.5 \
    SUGARKUBE_EXPECTED_ROLE=agent \
    SUGARKUBE_EXPECTED_PHASE=agent \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=confirmed ]]
  [[ "$output" =~ check=cli ]]
  [[ "$output" =~ resolve_method=cli ]]
}

@test "mdns self-check warns when enumeration misses but browse succeeds" {
  stub_avahi_browse_with_fixtures \
    "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt" \
    "${BATS_CWD}/tests/fixtures/avahi_browse_services_without_k3s.txt"

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
if [ "$#" -ne 1 ]; then
  echo "unexpected arguments" >&2
  exit 1
fi
printf '%s %s\n' "$1" "192.168.3.10"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=mdns_type_check ]]
  [[ "$output" =~ present=0 ]]
  [[ "$output" =~ severity=warn ]]
  [[ ! "$output" =~ reason=service_type_missing ]]
  [[ "$output" =~ outcome=ok ]]
}

@test "mdns self-check waits for active queries when instance appears within window" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
state_file="${BATS_TEST_TMPDIR}/browse-count"
count=0
if [ -f "${state_file}" ]; then
  count="$(cat "${state_file}")"
fi
case "${count}" in
  ''|*[!0-9]*) count=0 ;;
esac
count=$((count + 1))
printf '%s' "${count}" >"${state_file}"
if [ "${count}" -lt 3 ]; then
  exit 0
fi
cat <<'TXT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (agent);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt=cluster=sugar;txt=env=dev;txt=role=agent;txt=phase=agent
TXT
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "10.0.0.5"
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.5 \
    SUGARKUBE_EXPECTED_ROLE=agent \
    SUGARKUBE_EXPECTED_PHASE=agent \
    SUGARKUBE_SELFCHK_ATTEMPTS=5 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=100 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=100 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  [[ "$output" =~ attempts=3 ]]
}

@test "mdns self-check strips surrounding quotes before matching" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
cat <<'TXT'
=;eth0;IPv4;"k3s-sugar-dev@sugarkube0 (server)";"_k3s-sugar-dev._tcp";local;"sugarkube0.local";"10.0.0.5";6443;"txt=\"cluster=sugar\"";"txt=\"env=dev\"";"txt=\"role=server\"";"txt=\"phase=server\""
TXT
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "10.0.0.5"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.5 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  [[ "$output" =~ host=sugarkube0.local ]]
}

@test "mdns self-check accepts short host when EXPECTED_HOST has .local" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
cat <<'TXT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;sugarkube0;10.0.0.5;6443;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=phase=server
TXT
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "10.0.0.5"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.5 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
}

@test "mdns self-check handles spaces in instance name and TXT values" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
cat <<'TXT'
=;eth0;IPv4;"k3s-sugar-dev@sugarkube0 (bootstrap)";"_k3s-sugar-dev._tcp";local;"sugarkube0.local";"10.0.0.5";6443;"txt=\"cluster=sugar\"";"txt=\"env=dev\"";"txt=\"role=bootstrap\"";"txt=\"phase=server ready\""
TXT
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "10.0.0.5"
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.5 \
    SUGARKUBE_EXPECTED_ROLE=bootstrap \
    'SUGARKUBE_EXPECTED_PHASE=server ready' \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  [[ "$output" =~ host=sugarkube0.local ]]
}

@test "mdns self-check warns when browse succeeds but resolution lags" {
  stub_avahi_browse_with_fixtures \
    "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt" \
    "${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"

  stub_command avahi-resolve-host-name <<'EOS'
#!/usr/bin/env bash
exit 1
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
exit 1
EOS

  stub_command getent <<'EOS'
#!/usr/bin/env bash
exit 2
EOS

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=agent \
    SUGARKUBE_EXPECTED_PHASE=agent \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    LOG_LEVEL=debug \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=warn ]]
  [[ "$output" =~ reason=resolve_failed ]]
  [[ "$output" =~ host=sugarkube0.local ]]
}

@test "mdns self-check reports failure when no records appear" {
  stub_avahi_browse_with_fixtures \
    "${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt" \
    "${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "avahi-resolve should not be called" >&2
exit 2
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=2 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=10 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=10 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 1 ]
  [[ "$output" =~ outcome=fail ]]
  [[ "$output" =~ reason=browse_empty ]]
}

@test "mdns self-check fails fast when service type is missing" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_without_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
echo "unexpected browse invocation: $*" >&2
exit 2
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "avahi-resolve should not be called" >&2
exit 2
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=2 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=10 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=10 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 4 ]
  [[ "$output" =~ reason=service_type_missing ]]
  [[ "$output" =~ service_type=_k3s-sugar-dev._tcp ]]
  [[ "$stderr" =~ event=mdns_type_check ]]
  [[ "$stderr" =~ present=0 ]]
  [[ "$output" =~ available_types="_http._tcp,_ssh._tcp" ]]
}

@test "mdns self-check tolerates extra avahi-browse fields and anchors by type" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
cat <<'TXT'
=;wlan0;IPv6;ignored-instance;_https._tcp;local;otherhost.local;fe80::1;443;txt="foo=bar";garbage
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=phase=server
TXT
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "10.0.0.5"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.5 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
}

@test "mdns self-check returns distinct code on IPv4 mismatch to enable relaxed retry" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
cat <<'TXT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt=cluster=sugar;txt=env=dev;txt=role=server;txt=phase=server
TXT
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "10.0.0.5"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=10.0.0.99 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 5 ]
  [[ "$output" =~ outcome=fail ]]
  [[ "$output" =~ reason=ipv4_mismatch ]]
}

@test "mdns self-check ignores bootstrap advertisement when server required" {
  stub_avahi_browse_with_fixtures \
    "${BATS_CWD}/tests/fixtures/avahi_browse_bootstrap_only.txt" \
    "${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "avahi-resolve should not be called" >&2
exit 2
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 1 ]
  [[ "$output" =~ instance_not_found ]]
  [[ "$output" =~ reason=instance_not_found ]]
}

@test "mdns self-check falls back to CLI when dbus unsupported" {
  if ! command -v gdbus >/dev/null 2>&1; then
    skip "gdbus not available"
  fi

  stub_command gdbus <<'EOS'
#!/usr/bin/env bash
echo "dbus" >>"${BATS_TEST_TMPDIR}/gdbus.log"
exit 127
EOS

  stub_avahi_browse_with_fixtures \
    "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt" \
    "${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "192.168.3.10"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_MDNS_DBUS=1 \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  [ -f "${BATS_TEST_TMPDIR}/gdbus.log" ]
}

@test "mdns self-check falls back to CLI when dbus browser creation fails" {
  stub_command gdbus <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"${BATS_TEST_TMPDIR}/gdbus-calls.log"
for arg in "$@"; do
  if [ "${arg}" = "org.freedesktop.Avahi.Server.ServiceBrowserNew" ]; then
    exit 1
  fi
done
echo "unexpected gdbus invocation" >&2
exit 2
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
echo "cli" >>"${BATS_TEST_TMPDIR}/cli-path.log"
cat "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt"
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "192.168.3.10"
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    LOG_LEVEL=debug \
    SUGARKUBE_MDNS_DBUS=1 \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  [[ "$output" =~ fallback=cli ]]
  [ -f "${BATS_TEST_TMPDIR}/cli-path.log" ]
  grep -q "ServiceBrowserNew" "${BATS_TEST_TMPDIR}/gdbus-calls.log"
}

@test "mdns dbus self-check waits for avahi bus before browsing" {
  stub_command gdbus <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

mode="$1"
shift || true

ready_file="${BATS_TEST_TMPDIR}/avahi-ready.flag"
count_file="${BATS_TEST_TMPDIR}/introspect-count"

if [ "${mode}" = "introspect" ]; then
  count=0
  if [ -f "${count_file}" ]; then
    count="$(cat "${count_file}")"
  fi
  case "${count}" in
    ''|*[!0-9]*) count=0 ;;
  esac
  count=$((count + 1))
  printf '%s' "${count}" >"${count_file}"
  if [ "${count}" -lt 3 ]; then
    echo "org.freedesktop.DBus.Error.ServiceUnknown" >&2
    exit 1
  fi
  : >"${ready_file}"
  exit 0
fi

if [ "${mode}" = "call" ]; then
  method=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --method)
        method="$2"
        shift 2
        ;;
      --system)
        shift
        ;;
      --dest|--object-path)
        shift 2
        ;;
      *)
        shift
        ;;
    esac
  done

  case "${method}" in
    org.freedesktop.Avahi.Server.ServiceBrowserNew)
      if [ ! -f "${ready_file}" ]; then
        echo "org.freedesktop.DBus.Error.ServiceUnknown" >&2
        exit 1
      fi
      printf "(objectpath '/org/freedesktop/Avahi/ServiceBrowser/65537')\n"
      exit 0
      ;;
    org.freedesktop.Avahi.Server.ResolveService)
      output="(int32 0, int32 0, 'k3s-sugar-dev@sugarkube0 (server)',"
      output="${output} '_k3s-sugar-dev._tcp', 'local', 'sugarkube0.local',"
      output="${output} int32 0, '192.168.3.10', uint16 6443, array"
      output="${output} ['txt=\"cluster=sugar\"', 'txt=\"env=dev\"',"
      output="${output} 'txt=\"role=server\"', 'txt=\"phase=server\"'],"
      output="${output} uint32 0)"
      printf '%s\n' "${output}"
      exit 0
      ;;
    org.freedesktop.Avahi.Server.ResolveHostName)
      printf "(int32 0, int32 0, 'sugarkube0.local', '192.168.3.10', int32 0, uint32 0)\n"
      exit 0
      ;;
  esac
fi

echo "unexpected gdbus invocation" >&2
exit 2
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    LOG_LEVEL=info \
    SUGARKUBE_MDNS_DBUS=1 \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck_dbus.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=avahi_dbus_ready\ outcome=ok ]]
  [[ "$output" =~ event=mdns_selfcheck\ outcome=ok ]]
  [[ ! "$stderr" =~ browser_create_failed ]]
  [ -f "${BATS_TEST_TMPDIR}/introspect-count" ]
  count_value="$(cat "${BATS_TEST_TMPDIR}/introspect-count")"
  [[ "$count_value" =~ ^[0-9]+$ ]]
  (( count_value >= 3 ))
}

@test "mdns absence gate confirms wipe leaves no advertisements" {
  stub_command hostname <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-s" ]; then
  printf '%s\n' sugarkube0
  exit 0
fi
printf '%s\n' sugarkube0.local
EOS

  stub_command ip <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-4" ] && [ "$2" = "-o" ] && [ "$3" = "addr" ] && [ "$4" = "show" ]; then
  printf '2: eth0    inet 192.168.3.10/24\n'
  exit 0
fi
if [ "$1" = "-o" ] && [ "$2" = "link" ] && [ "$3" = "show" ] && [ "$4" = "up" ]; then
  printf '2: eth0: <UP>\n'
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
services_fixture="${BATS_CWD}/tests/fixtures/avahi_browse_services_with_k3s.txt"
if [ "$#" -gt 0 ] && [ "${!#}" = "_services._dns-sd._udp" ]; then
  cat "${services_fixture}"
  exit 0
fi
echo "avahi-browse $*" >>"${BATS_TEST_TMPDIR}/avahi-browse.log"
cat "${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt"
EOS

  stub_command sleep <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
cat <<'SCRIPT'
#!/usr/bin/env sh
exit 0
SCRIPT
EOS

  stub_command avahi-publish <<'EOS'
#!/usr/bin/env bash
sleep 60 &
pid=$!
echo "${pid}" >>"${BATS_TEST_TMPDIR}/publish.log"
wait "$pid"
EOS

  stub_command avahi-publish-address <<'EOS'
#!/usr/bin/env bash
sleep 60 &
pid=$!
echo "${pid}" >>"${BATS_TEST_TMPDIR}/publish.log"
wait "$pid"
EOS

  mkdir -p "${BATS_TEST_TMPDIR}/run" "${BATS_TEST_TMPDIR}/avahi/services"
  token_path="${BATS_TEST_TMPDIR}/node-token"
  printf '%s\n' "demo-token" >"${token_path}"
  configure_stub="${BATS_TEST_TMPDIR}/configure-avahi-stub.sh"
  cat <<'EOS' >"${configure_stub}"
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "${configure_stub}"

  api_ready_stub="$(create_api_ready_stub)"

  run env \
    ALLOW_NON_ROOT=1 \
    LOG_LEVEL=info \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_MDNS_ABSENCE_DBUS=0 \
    SUGARKUBE_MDNS_DBUS=0 \
    SUGARKUBE_MDNS_WIRE_PROOF=0 \
    SUGARKUBE_CONFIGURE_AVAHI_BIN="${configure_stub}" \
    SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    SUGARKUBE_MDNS_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    AVAHI_CONF_PATH="${BATS_TEST_TMPDIR}/avahi.conf" \
    SUGARKUBE_AVAHI_SERVICE_DIR="${BATS_TEST_TMPDIR}/avahi/services" \
    SUGARKUBE_MDNS_FIXTURE_FILE="${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt" \
    SUGARKUBE_MDNS_PUBLISH_ADDR=192.168.3.10 \
    SUGARKUBE_SERVERS=0 \
    SUGARKUBE_NODE_TOKEN_PATH="${token_path}" \
    DISCOVERY_WAIT_SECS=0 \
    DISCOVERY_ATTEMPTS=1 \
    SUGARKUBE_API_READY_CHECK_BIN="${api_ready_stub}" \
    "${BATS_CWD}/scripts/k3s-discover.sh"

  [ "$status" -ne 0 ]
  [[ "$output" =~ mdns_absence_confirmed=1 ]]
  calls=$(wc -l <"${BATS_TEST_TMPDIR}/avahi-browse.log")
  [ "${calls}" -ge 2 ]
}

@test "mdns self-check succeeds via dbus backend" {
  stub_command gdbus <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
method=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--method" ]; then
    shift
    method="${1:-}"
    break
  fi
  shift
done
case "${method}" in
  org.freedesktop.Avahi.Server.ServiceBrowserNew)
    echo "(objectpath \"/Browser0\")"
    ;;
  org.freedesktop.Avahi.Server.ResolveService)
    cat <<'OUT'
(0, 0, "k3s-sugar-dev@sugarkube0.local (server)", "_k3s-sugar-dev._tcp", "local", "sugarkube0.local", 0, "192.168.3.10", 6443, ["role=server", "phase=server"], 0)
OUT
    ;;
  org.freedesktop.Avahi.Server.ResolveHostName)
    cat <<'OUT'
(0, 0, "sugarkube0.local", "192.168.3.10", 0, 0)
OUT
    ;;
  *)
    echo "unexpected method: ${method}" >&2
    exit 1
    ;;
esac
echo "${method}" >>"${BATS_TEST_TMPDIR}/gdbus-calls.log"
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
echo "CLI path should not execute" >&2
exit 1
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "CLI resolver should not execute" >&2
exit 1
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
# Stub curl to simulate successful API readiness check
exit 0
EOS
  run env \
    SUGARKUBE_MDNS_DBUS=1 \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    SUGARKUBE_EXPECTED_HOST=sugarkube0.local \
    SUGARKUBE_EXPECTED_IPV4=192.168.3.10 \
    SUGARKUBE_EXPECTED_ROLE=server \
    SUGARKUBE_EXPECTED_PHASE=server \
    SUGARKUBE_SELFCHK_ATTEMPTS=1 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=0 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  [[ "$output" =~ host=sugarkube0.local ]]
  [[ "$output" =~ ipv4=192.168.3.10 ]]
  [[ "$output" =~ port=6443 ]]
  grep -q "ResolveService" "${BATS_TEST_TMPDIR}/gdbus-calls.log"
  ! grep -q "CLI" "${BATS_TEST_TMPDIR}/gdbus-calls.log"
}
