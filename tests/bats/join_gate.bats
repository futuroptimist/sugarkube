#!/usr/bin/env bats

load helpers/path_stub

setup() {
  ORIGINAL_PATH="$PATH"
  unset _BATS_PATH_STUB_DIR
  setup_path_stub_dir
  PATH="${_BATS_PATH_STUB_DIR}:${ORIGINAL_PATH}"
}

teardown() {
  PATH="$ORIGINAL_PATH"
}

@test "join gate acquire and release manage publisher state" {
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
exit 1
EOS

  stub_command avahi-publish-service <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
echo $$ >"${BATS_TEST_TMPDIR}/publisher.pid"
trap 'echo terminated >"${BATS_TEST_TMPDIR}/publisher.status"; exit 0' TERM INT
while true; do
  sleep 0.1
done
EOS

  runtime="${BATS_TEST_TMPDIR}/run"

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime}" \
    SUGARKUBE_CLUSTER=demo \
    SUGARKUBE_ENV=test \
    "${BATS_CWD}/scripts/join_gate.sh" wait
  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=clear ]]

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime}" \
    SUGARKUBE_CLUSTER=demo \
    SUGARKUBE_ENV=test \
    "${BATS_CWD}/scripts/join_gate.sh" acquire
  [ "$status" -eq 0 ]
  [[ "$output" =~ action=acquire ]]

  state_file="${runtime}/join-gate-demo-test.state"
  [ -f "${state_file}" ]

  publisher_pid="$(grep '^pid=' "${state_file}" | cut -d'=' -f2)"
  [ -n "${publisher_pid}" ]
  kill -0 "${publisher_pid}"

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime}" \
    SUGARKUBE_CLUSTER=demo \
    SUGARKUBE_ENV=test \
    "${BATS_CWD}/scripts/join_gate.sh" release
  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]

  ! kill -0 "${publisher_pid}" 2>/dev/null
  [ ! -f "${state_file}" ]
  [ "$(cat "${BATS_TEST_TMPDIR}/publisher.status")" = "terminated" ]
}

@test "join gate wait retries while lock is present" {
  stub_command avahi-publish-service <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
count_file="${BATS_TEST_TMPDIR}/browse-count"
count=0
if [ -f "${count_file}" ]; then
  count="$(cat "${count_file}")"
fi
count=$((count + 1))
printf '%s' "${count}" >"${count_file}"
if [ "${count}" -lt 3 ]; then
  cat <<'OUT'
=;eth0;IPv4;k3s join gate;_k3s-join-lock._tcp;local;sugarkube.local;192.0.2.20;1234;
OUT
  exit 0
fi
exit 1
EOS

  runtime="${BATS_TEST_TMPDIR}/run"

  run env \
    SUGARKUBE_RUNTIME_DIR="${runtime}" \
    SUGARKUBE_CLUSTER=demo \
    SUGARKUBE_ENV=test \
    "${BATS_CWD}/scripts/join_gate.sh" wait
  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=busy ]]
  [[ "$output" =~ outcome=clear ]]
  [ "$(cat "${BATS_TEST_TMPDIR}/browse-count")" -ge 3 ]
}
