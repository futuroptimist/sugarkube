#!/usr/bin/env bats

load helpers/path_stub

bats_require_minimum_version 1.5.0

setup() {
  setup_path_stub_dir
}

prepare_mdns_publish_static_environment() {
  SERVICE_DIR="${BATS_TEST_TMPDIR}/services"
  SERVICE_FILE="${SERVICE_DIR}/k3s-sugar-dev.service"
  HOSTS_PATH="${BATS_TEST_TMPDIR}/avahi.hosts"
  JOURNAL_LOG="${BATS_TEST_TMPDIR}/journal.log"
  RENAME_MARKER="${BATS_TEST_TMPDIR}/rename-marker"
  mkdir -p "${SERVICE_DIR}" "${BATS_TEST_TMPDIR}/run"
  : >"${JOURNAL_LOG}"
  : >"${RENAME_MARKER}"

  export SUGARKUBE_CLUSTER="sugar"
  export SUGARKUBE_ENV="dev"
  export HOSTNAME="test-node.local"
  export ROLE="bootstrap"
  export PHASE="bootstrap"
  export PORT=6443
  export LEADER="test-node.local"
  export SUGARKUBE_EXPECTED_IPV4="10.0.0.10"
  export SUGARKUBE_MDNS_INTERFACE="eth0"
  export SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run"
  export SUGARKUBE_AVAHI_WAIT_TIMEOUT=1
  unset SUGARKUBE_SKIP_SYSTEMCTL
  export SUGARKUBE_AVAHI_SERVICE_DIR="${SERVICE_DIR}"
  export SUGARKUBE_AVAHI_SERVICE_FILE="${SERVICE_FILE}"
  export SUGARKUBE_AVAHI_HOSTS_PATH="${HOSTS_PATH}"
  export TEST_JOURNAL_LOG="${JOURNAL_LOG}"
  export TEST_RENAME_MARKER="${RENAME_MARKER}"
  export ALLOW_NON_ROOT=1

  real_mv="$(command -v mv)"
  real_chmod="$(command -v chmod)"

  stub_command systemctl <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  is-active)
    exit 1
    ;;
  reload|restart)
    exit 0
    ;;
  *)
    exit 0
    ;;
 esac
EOS

  stub_command avahi-resolve-host-name <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
target="${1:-}"
hosts_file="${SUGARKUBE_AVAHI_HOSTS_PATH:-}"
if [ -n "${hosts_file}" ] && [ -f "${hosts_file}" ] && grep -Fq "${target}" "${hosts_file}"; then
  printf '%s %s\n' "${target}" "${SUGARKUBE_EXPECTED_IPV4}"
  exit 0
fi
exit 1
EOS

  stub_command avahi-resolve <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
host=""
for arg in "$@"; do
  case "${arg}" in
    -n|--timeout=*|-4)
      ;;
    *)
      if [ -z "${host}" ]; then
        host="${arg}"
      fi
      ;;
  esac
 done
if [ -z "${host}" ]; then
  host="${SRV_HOST:-${HOSTNAME}}"
fi
printf '%s %s\n' "${host}" "${SUGARKUBE_EXPECTED_IPV4}"
EOS

  stub_command avahi-set-host-name <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  stub_command getent <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "hosts" ]; then
  hosts_file="${SUGARKUBE_AVAHI_HOSTS_PATH:-}"
  if [ -n "${hosts_file}" ] && [ -f "${hosts_file}" ] && grep -Fq "${2}" "${hosts_file}"; then
    printf '%s %s\n' "${SUGARKUBE_EXPECTED_IPV4}" "$2"
    exit 0
  fi
  exit 2
fi
exit 1
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
service="${!#}"
cat <<TXT
=;eth0;IPv4;k3s-${SUGARKUBE_CLUSTER}-${SUGARKUBE_ENV}@${SRV_HOST:-${HOSTNAME}} (${ROLE});${service};local;${SRV_HOST:-${HOSTNAME}};${SUGARKUBE_EXPECTED_IPV4};6443;txt=cluster=${SUGARKUBE_CLUSTER};txt=env=${SUGARKUBE_ENV};txt=role=${ROLE};txt=phase=${PHASE}
TXT
exit 0
EOS

  stub_command curl <<'EOS'
#!/usr/bin/env bash
exit 7
EOS

  stub_command journalctl <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
log_path="${TEST_JOURNAL_LOG:-}"
service_display="k3s-${SUGARKUBE_CLUSTER}-${SUGARKUBE_ENV}@${SRV_HOST:-${HOSTNAME}} (${ROLE})"
mode="missing"
if [ -n "${SUGARKUBE_AVAHI_SERVICE_FILE:-}" ] && [ -e "${SUGARKUBE_AVAHI_SERVICE_FILE}" ]; then
  mode="$(stat -c '%a' "${SUGARKUBE_AVAHI_SERVICE_FILE}" 2>/dev/null || echo 'missing')"
fi
if [ -n "${log_path}" ]; then
  printf '%s mode=%s\n' "${service_display}" "${mode}" >>"${log_path}"
fi
if [ "${mode}" = "600" ] || [ "${mode}" = "0600" ]; then
  message="Service \"${service_display}\" failed: Permission denied"
  printf '%s\n' "${message}"
  if [ -n "${log_path}" ]; then
    printf '%s\n' "${message}" >>"${log_path}"
  fi
  exit 0
fi
rename_state=""
if [ -n "${TEST_RENAME_MARKER:-}" ] && [ -f "${TEST_RENAME_MARKER}" ]; then
  rename_state="$(cat "${TEST_RENAME_MARKER}" 2>/dev/null || true)"
fi
if [ "${rename_state}" = "atomic" ]; then
  message="Service \"${service_display}\" successfully established."
else
  message="Service \"${service_display}\" vanished while publishing."
fi
printf '%s\n' "${message}"
if [ -n "${log_path}" ]; then
  printf '%s\n' "${message}" >>"${log_path}"
fi
exit 0
EOS

  stub_command chmod <<EOS
#!/usr/bin/env bash
set -euo pipefail
real_chmod="${real_chmod}"
force="\${TEST_CHMOD_FORCE_MODE:-}"
mode="\$1"
shift
if [ -n "\${force}" ]; then
  mode="\${force}"
fi
exec "${real_chmod}" "\${mode}" "\$@"
EOS

  stub_command mv <<EOS
#!/usr/bin/env bash
set -euo pipefail
real_mv="${real_mv}"
args=("\$@")
shifted=("\$@")
while [ "\${#shifted[@]}" -gt 0 ]; do
  candidate="\${shifted[0]}"
  case "\${candidate}" in
    -*)
      shifted=("\${shifted[@]:1}")
      ;;
    *)
      break
      ;;
  esac
done
if [ "\${#shifted[@]}" -ge 2 ]; then
  src="\${shifted[0]}"
  dest="\${shifted[1]}"
  if [ -n "\${TEST_RENAME_MARKER:-}" ] && [ "\${dest}" = "\${SUGARKUBE_AVAHI_SERVICE_FILE:-}" ] && [[ "\${src}" == "\${SUGARKUBE_AVAHI_SERVICE_DIR:-}"/.k3s-mdns.* ]]; then
    printf 'atomic' >"\${TEST_RENAME_MARKER}"
  fi
fi
exec "${real_mv}" "\${args[@]}"
EOS
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
      cat <<'OUT'
('<node>\n  <node name="org/freedesktop/Avahi"/>\n</node>',)
OUT
      ;;
    /org/freedesktop/Avahi)
      cat <<'OUT'
('<node>\n  <node name="Server"/>\n</node>',)
OUT
      ;;
    /org/freedesktop/Avahi/Server)
      cat <<'OUT'
('<node>\n  <node name="EntryGroup0"/>\n</node>',)
OUT
      ;;
    /org/freedesktop/Avahi/Server/EntryGroup0)
      cat <<'OUT'
('<node/>',)
OUT
      ;;
    *)
      cat <<'OUT'
('<node/>',)
OUT
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

@test "mdns_publish_static surfaces permission denied when service unreadable" {
  prepare_mdns_publish_static_environment
  rm -f "${SERVICE_FILE}" "${HOSTS_PATH}" || true
  : >"${TEST_RENAME_MARKER}"
  : >"${TEST_JOURNAL_LOG}"
  export TEST_CHMOD_FORCE_MODE=0600

  run --separate-stderr bash "${BATS_CWD}/scripts/mdns_publish_static.sh"
  script_status=$status
  script_stderr=$stderr

  [ "$script_status" -ne 0 ]
  [[ "$script_stderr" =~ Timed\ out\ waiting\ for\ Avahi\ to\ publish ]]
  run grep -F "Permission denied" "${TEST_JOURNAL_LOG}"
  [ "$status" -eq 0 ]
}

@test "mdns_publish_static writes atomically without journal churn" {
  prepare_mdns_publish_static_environment
  rm -f "${SERVICE_FILE}" "${HOSTS_PATH}" || true
  : >"${TEST_RENAME_MARKER}"
  : >"${TEST_JOURNAL_LOG}"
  unset TEST_CHMOD_FORCE_MODE

  run --separate-stderr bash "${BATS_CWD}/scripts/mdns_publish_static.sh"
  script_status=$status

  [ "$script_status" -eq 0 ]
  [ -f "${SERVICE_FILE}" ]
  [ -f "${HOSTS_PATH}" ]
  grep -F "successfully established" "${TEST_JOURNAL_LOG}"
  if grep -Fq "vanished" "${TEST_JOURNAL_LOG}"; then
    false
  fi
  if grep -Fq "Permission denied" "${TEST_JOURNAL_LOG}"; then
    false
  fi
  [ -f "${TEST_RENAME_MARKER}" ]
  grep -F "atomic" "${TEST_RENAME_MARKER}"

  expected_service="${BATS_CWD}/tests/fixtures/avahi_service_bootstrap.xml"
  run diff -u "${expected_service}" "${SERVICE_FILE}"
  [ "$status" -eq 0 ]

  expected_hosts="${BATS_CWD}/tests/fixtures/avahi_hosts_expected.txt"
  run diff -u "${expected_hosts}" "${HOSTS_PATH}"
  [ "$status" -eq 0 ]
}
