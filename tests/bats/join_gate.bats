#!/usr/bin/env bats

load helpers/path_stub

setup() {
  ORIGINAL_PATH="$PATH"
  unset _BATS_PATH_STUB_DIR
  PATH="$ORIGINAL_PATH"
  setup_path_stub_dir
  export SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run"
  mkdir -p "${SUGARKUBE_RUNTIME_DIR}"
}

teardown() {
  PATH="$ORIGINAL_PATH"
}

@test "join gate acquires and releases lock" {
  publish_log="${BATS_TEST_TMPDIR}/publish.log"
  stub_command avahi-browse <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
exit 1
EOS

  stub_command avahi-publish-service <<EOS
#!/usr/bin/env bash
set -euo pipefail
echo "$@" >> "${publish_log}"
trap 'exit 0' TERM INT
while true; do sleep 1; done
EOS

  run "${BATS_CWD}/scripts/join_gate.sh" acquire
  [ "$status" -eq 0 ]

  pid_file="${SUGARKUBE_RUNTIME_DIR}/join-gate.pid"
  [ -f "${pid_file}" ]
  lock_pid="$(cat "${pid_file}")"
  [ -n "${lock_pid}" ]
  kill -0 "${lock_pid}"

  run "${BATS_CWD}/scripts/join_gate.sh" release
  [ "$status" -eq 0 ]
  [ ! -f "${pid_file}" ]
  ! kill -0 "${lock_pid}" 2>/dev/null

  publish_contents="$(cat "${publish_log}" 2>/dev/null || true)"
  [[ "${publish_contents}" =~ _k3s-join-lock._tcp ]]
}

@test "join gate wait blocks until lock clears" {
  counter_file="${BATS_TEST_TMPDIR}/counter"
  stub_command avahi-browse <<EOS
#!/usr/bin/env bash
set -euo pipefail
counter_file="${counter_file}"
release_after="\${JOIN_GATE_STUB_RELEASE_AFTER:-3}"
count=0
if [ -f "${counter_file}" ]; then
  count="\$(cat "${counter_file}")"
fi
count=$((count + 1))
printf '%s' "${count}" >"${counter_file}"
if [ "${count}" -lt "${release_after}" ]; then
  cat <<'OUT'
=;eth0;IPv4;k3s join gate;_k3s-join-lock._tcp;local;host.local;192.0.2.1;5555
OUT
  exit 0
fi
exit 1
EOS

  run env JOIN_GATE_STUB_RELEASE_AFTER=4 "${BATS_CWD}/scripts/join_gate.sh" wait
  [ "$status" -eq 0 ]
  attempts="$(cat "${counter_file}")"
  [ "${attempts}" -eq 4 ]
}
