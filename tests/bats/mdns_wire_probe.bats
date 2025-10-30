#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
}

@test "mdns_wire_probe reports established via dbus" {
  stub_command gdbus <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" != "call" ]; then
  echo "unexpected invocation" >&2
  exit 1
fi
path=""
method=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --object-path)
      path="$2"
      shift 2
      ;;
    --method)
      method="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [ "${method}" = "org.freedesktop.DBus.Introspectable.Introspect" ]; then
  case "${path}" in
    /)
      printf "('<node>\n  <node name=\"org/freedesktop/Avahi\"/>\n</node>',)\n"
      ;;
    /org/freedesktop/Avahi)
      printf "('<node>\n  <node name=\"Server\"/>\n</node>',)\n"
      ;;
    /org/freedesktop/Avahi/Server)
      printf "('<node>\n  <node name=\"EntryGroup0\"/>\n</node>',)\n"
      ;;
    /org/freedesktop/Avahi/Server/EntryGroup0)
      printf "('<node/>',)\n"
      ;;
    *)
      printf "('<node/>',)\n"
      ;;
  esac
elif [ "${method}" = "org.freedesktop.Avahi.EntryGroup.GetState" ]; then
  printf "(2,)\n"
else
  printf "()\n"
fi
STUB

  run "${BATS_CWD}/scripts/mdns_wire_probe.sh"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [[ "${lines[0]}" =~ status=established ]]
  [[ "${lines[0]}" =~ dbus_rc=0 ]]
  [[ "${lines[0]}" =~ dbus_summary= ]]
}

@test "mdns_wire_probe falls back to cli when dbus unavailable" {
  stub_command gdbus <<'STUB'
#!/usr/bin/env bash
exit 1
STUB

  stub_command tcpdump <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  stub_command avahi-browse <<'STUB'
#!/usr/bin/env bash
printf 'no-visible-results\n'
exit 0
STUB

  run "${BATS_CWD}/scripts/mdns_wire_probe.sh"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [[ "${lines[0]}" =~ status=indeterminate ]]
  [[ "${lines[0]}" =~ reason=dbus_error ]]
  [[ "${lines[0]}" =~ browse_output= ]]
}

@test "mdns publish static reports permission issues and writes readable service" {
  service_dir="${BATS_TEST_TMPDIR}/avahi/services"
  hosts_path="${BATS_TEST_TMPDIR}/avahi/hosts"
  mkdir -p "${service_dir}"
  mkdir -p "$(dirname "${hosts_path}")"
  service_file="${service_dir}/k3s-sugar-dev.service"
  journal_log="${BATS_TEST_TMPDIR}/journal.log"

  cat "${BATS_CWD}/tests/fixtures/avahi_service_bootstrap.xml" >"${service_file}"
  chmod 0600 "${service_file}"

  stub_command journalctl <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
: "${TEST_SERVICE_FILE:?}"
: "${TEST_SERVICE_DISPLAY:?}"
: "${TEST_SERVICE_TYPE:?}"
: "${TEST_JOURNAL_LOG:?}"

mode="$(stat -c '%a' "${TEST_SERVICE_FILE}")"
if [ "${mode}" = "600" ]; then
  msg="Failed to add service \"${TEST_SERVICE_DISPLAY}\" of type \"${TEST_SERVICE_TYPE}\": Permission denied"
  printf '%s\n' "${msg}" | tee -a "${TEST_JOURNAL_LOG}"
else
  msg="Service \"${TEST_SERVICE_DISPLAY}\" successfully established."
  printf '%s\n' "${msg}" | tee -a "${TEST_JOURNAL_LOG}"
fi
STUB

  run env \
    TEST_SERVICE_FILE="${service_file}" \
    TEST_SERVICE_DISPLAY="k3s-sugar-dev@sugarkube0.local (bootstrap)" \
    TEST_SERVICE_TYPE="_k3s-sugar-dev._tcp" \
    TEST_JOURNAL_LOG="${journal_log}" \
    journalctl -u avahi-daemon --since "@0" --no-pager

  [ "$status" -eq 0 ]
  [[ "$output" =~ Permission\ denied ]]

  rm -f "${service_file}"

  stub_command getent <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "hosts" ]; then
  printf '192.0.2.10 sugarkube0.local\n'
  exit 0
fi
exit 1
STUB

  stub_command avahi-resolve-host-name <<'STUB'
#!/usr/bin/env bash
host="$1"
shift || true
if [ "${host}" = "sugarkube0.local" ]; then
  printf '%s\t%s\n' "${host}" "192.0.2.10"
  exit 0
fi
exit 2
STUB

  stub_command avahi-set-host-name <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  stub_command systemctl <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  run env \
    SUGARKUBE_CLUSTER=sugar \
    SUGARKUBE_ENV=dev \
    HOSTNAME=sugarkube0.local \
    ROLE=bootstrap \
    PORT=6443 \
    SUGARKUBE_AVAHI_SERVICE_DIR="${service_dir}" \
    SUGARKUBE_AVAHI_HOSTS_PATH="${hosts_path}" \
    SUGARKUBE_EXPECTED_IPV4=192.0.2.10 \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_AVAHI_WAIT_TIMEOUT=1 \
    TEST_SERVICE_FILE="${service_file}" \
    TEST_SERVICE_DISPLAY="k3s-sugar-dev@sugarkube0.local (bootstrap)" \
    TEST_SERVICE_TYPE="_k3s-sugar-dev._tcp" \
    TEST_JOURNAL_LOG="${journal_log}" \
    "${BATS_CWD}/scripts/mdns_publish_static.sh"

  [ "$status" -eq 0 ]
  [ -f "${service_file}" ]
  [ "$(stat -c '%a' "${service_file}")" = "644" ]

  run diff -u "${BATS_CWD}/tests/fixtures/avahi_service_bootstrap.xml" "${service_file}"
  [ "$status" -eq 0 ]

  if grep -F "Permission denied" "${journal_log}" >/dev/null 2>&1; then
    echo "Unexpected permission denial in journal output" >&2
    return 1
  fi
  if grep -F "vanished" "${journal_log}" >/dev/null 2>&1; then
    echo "Unexpected vanished entry in journal output" >&2
    return 1
  fi
  grep -F "successfully established" "${journal_log}" >/dev/null
}
