#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
}

@test "join gate acquire and release cleans up publisher" {
  runtime_dir="${BATS_TEST_TMPDIR}/run"
  mkdir -p "${runtime_dir}"

  publish_pid_file="${BATS_TEST_TMPDIR}/publisher.pid"
  publish_log="${BATS_TEST_TMPDIR}/publisher.log"

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  stub_command avahi-publish-service <<EOS
#!/usr/bin/env bash
set -euo pipefail
echo "$$" >"${publish_pid_file}"
trap 'echo TERM >>"${publish_log}"; exit 0' TERM INT
while true; do
  sleep 0.1
done
EOS

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime_dir}" \
    "${BATS_CWD}/scripts/join_gate.sh" acquire

  [ "$status" -eq 0 ]
  [ -f "${runtime_dir}/join-gate-avahi.pid" ]
  pid_from_runtime="$(cat "${runtime_dir}/join-gate-avahi.pid")"
  pid_from_publish="$(cat "${publish_pid_file}")"
  [ "${pid_from_runtime}" = "${pid_from_publish}" ]
  kill -0 "${pid_from_publish}"

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime_dir}" \
    "${BATS_CWD}/scripts/join_gate.sh" release

  [ "$status" -eq 0 ]
  [ ! -f "${runtime_dir}/join-gate-avahi.pid" ]
  run cat "${publish_log}"
  [ "$status" -eq 0 ]
  [[ "${output}" =~ TERM ]]
  ! kill -0 "${pid_from_publish}" 2>/dev/null
}

@test "join gate wait polls until lock disappears" {
  runtime_dir="${BATS_TEST_TMPDIR}/run"
  mkdir -p "${runtime_dir}"

  state_file="${BATS_TEST_TMPDIR}/browse-count"

  stub_command avahi-browse <<EOS
#!/usr/bin/env bash
state_file="${state_file}"
count=0
if [ -f "${state_file}" ]; then
  count="$(cat "${state_file}")"
fi
count=$((count + 1))
echo "${count}" >"${state_file}"
if [ "${count}" -lt 3 ]; then
  echo "=;eth0;IPv4;join-lock;_k3s-join-lock._tcp;local;example.local;192.0.2.10;1234"
fi
exit 0
EOS

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime_dir}" \
    "${BATS_CWD}/scripts/join_gate.sh" wait

  [ "$status" -eq 0 ]
  count="$(cat "${state_file}")"
  [ "${count}" -ge 3 ]
}
