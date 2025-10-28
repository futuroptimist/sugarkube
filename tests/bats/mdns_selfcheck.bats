#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
}

@test "mdns self-check succeeds when instance is discoverable" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt"
EOS

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
    SUGARKUBE_MDNS_DBUS=0 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=mdns_selfcheck ]]
  [[ "$output" =~ host=sugarkube0.local ]]
  [[ "$output" =~ ipv4=192.168.3.10 ]]
}

@test "mdns self-check strips surrounding quotes before matching" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat <<'TXT'
=;eth0;IPv4;"k3s-sugar-dev@sugarkube0 (server)";"_k3s-sugar-dev._tcp";local;"sugarkube0.local";"10.0.0.5";6443;"txt=\"k3s=1\"";"txt=\"cluster=sugar\"";"txt=\"env=dev\"";"txt=\"role=server\"";"txt=\"phase=server\""
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
cat <<'TXT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt=\"k3s=1\" txt=\"cluster=sugar\" txt=\"env=dev\" txt=\"role=server\" txt=\"phase=server\"
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

@test "mdns self-check reports failure when no records appear" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat "${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt"
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "avahi-resolve should not be called" >&2
exit 2
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

@test "mdns self-check tolerates extra avahi-browse fields and anchors by type" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat <<'TXT'
=;wlan0;IPv6;ignored-instance;_https._tcp;local;otherhost.local;fe80::1;443;txt="foo=bar";garbage
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt="k3s=1";txt="cluster=sugar";txt="env=dev";txt="role=server";txt="phase=server"
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
cat <<'TXT'
=;eth0;IPv4;k3s-sugar-dev@sugarkube0 (server);_k3s-sugar-dev._tcp;local;sugarkube0.local;10.0.0.5;6443;txt="k3s=1";txt="cluster=sugar";txt="env=dev";txt="role=server";txt="phase=server"
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
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat "${BATS_CWD}/tests/fixtures/avahi_browse_bootstrap_only.txt"
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
echo "avahi-resolve should not be called" >&2
exit 2
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

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt"
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
if [ "$1" = "-n" ]; then
  shift
fi
printf '%s %s\n' "$1" "192.168.3.10"
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

@test "mdns self-check falls back to CLI when dbus browser fails" {
  if ! command -v gdbus >/dev/null 2>&1; then
    skip "gdbus not available"
  fi

  stub_command gdbus <<'EOS'
#!/usr/bin/env bash
echo "$@" >>"${BATS_TEST_TMPDIR}/gdbus.log"
if printf '%s' "$@" | grep -q "ServiceBrowserNew"; then
  exit 1
fi
echo "unexpected gdbus invocation" >&2
exit 3
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat "${BATS_CWD}/tests/fixtures/avahi_browse_ok.txt"
EOS

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
  grep -q "ServiceBrowserNew" "${BATS_TEST_TMPDIR}/gdbus.log"
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

@test "mdns absence gate confirms wipe after consecutive empty scans" {
  configure_stub="${BATS_TEST_TMPDIR}/configure-avahi-stub.sh"
  cat <<'EOS' >"${configure_stub}"
#!/usr/bin/env bash
exit 0
EOS
  chmod +x "${configure_stub}"

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
cat "${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt"
EOS

  run env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_CONFIGURE_AVAHI_BIN="${configure_stub}" \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run" \
    SUGARKUBE_MDNS_FIXTURE_FILE="${BATS_CWD}/tests/fixtures/avahi_browse_empty.txt" \
    SUGARKUBE_MDNS_PUBLISH_ADDR=192.168.3.10 \
    SUGARKUBE_MDNS_DBUS=0 \
    SUGARKUBE_MDNS_ABSENCE_DBUS=0 \
    SUGARKUBE_MDNS_WIRE_PROOF=0 \
    SUGARKUBE_MDNS_HOST=sugarkube0.local \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    DISCOVERY_ATTEMPTS=1 \
    DISCOVERY_WAIT_SECS=0 \
    "${BATS_CWD}/scripts/k3s-discover.sh" --test-absence-gate-only

  [ "$status" -eq 0 ]
  [[ "$output" =~ mdns_absence_confirmed=1 ]]
}
