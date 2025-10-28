#!/usr/bin/env bats

load helpers/path_stub

setup() {
  ORIGINAL_PATH="$PATH"
  PATH="$ORIGINAL_PATH"
  setup_path_stub_dir

  export SUGARKUBE_RUNTIME_DIR="${BATS_TEST_TMPDIR}/run"
  mkdir -p "${SUGARKUBE_RUNTIME_DIR}"
  export SUGARKUBE_JOIN_GATE_BACKOFF_START=1
  export SUGARKUBE_JOIN_GATE_BACKOFF_MAX=1

  LOCK_FILE="${BATS_TEST_TMPDIR}/lock"
  PUBLISH_LOG="${BATS_TEST_TMPDIR}/publish.log"
  PUBLISH_PID_FILE="${BATS_TEST_TMPDIR}/publisher.pid"

  stub_command avahi-browse <<EOF_INNER
#!/usr/bin/env bash
set -euo pipefail
lock_file="${LOCK_FILE}"
if [[ "$*" == *"_k3s-join-lock._tcp"* ]]; then
  if [ -f "${lock_file}" ]; then
    cat <<'OUT'
=;eth0;IPv4;k3s join lock;k3s join lock;_k3s-join-lock._tcp;local;host.local;127.0.0.1;1234
OUT
  fi
  exit 0
fi
exit 0
EOF_INNER

  stub_command avahi-publish-service <<EOF_PUBLISH
#!/usr/bin/env bash
set -euo pipefail
lock_file="${LOCK_FILE}"
log_file="${PUBLISH_LOG}"
pid_file="${PUBLISH_PID_FILE}"
printf '%s\n' "$*" >>"${log_file}"
echo "$$" >"${pid_file}"
touch "${lock_file}"
trap 'printf "TERM\n" >>"'"${PUBLISH_LOG}"'"; rm -f "${lock_file}"; exit 0' TERM INT
while true; do sleep 1; done
EOF_PUBLISH
}

teardown() {
  PATH="$ORIGINAL_PATH"
  if [ -f "${PUBLISH_PID_FILE}" ]; then
    pid="$(cat "${PUBLISH_PID_FILE}" 2>/dev/null || true)"
    if [ -n "${pid}" ]; then
      kill "${pid}" 2>/dev/null || true
    fi
  fi
  rm -f "${LOCK_FILE}" "${PUBLISH_PID_FILE}"
}

@test "join gate acquire and release manage lock lifecycle" {
  run "${BATS_CWD}/scripts/join_gate.sh" acquire
  [ "$status" -eq 0 ]

  pid_file="${SUGARKUBE_RUNTIME_DIR}/join-gate.pid"
  [ -f "${pid_file}" ]
  publisher_pid="$(cat "${pid_file}" 2>/dev/null)"
  [ -n "${publisher_pid}" ]
  [ -f "${LOCK_FILE}" ]

  run "${BATS_CWD}/scripts/join_gate.sh" release
  [ "$status" -eq 0 ]
  [ ! -f "${pid_file}" ]
  [ ! -f "${LOCK_FILE}" ]

  publish_log_contents="$(cat "${PUBLISH_LOG}" 2>/dev/null)"
  [[ "${publish_log_contents}" =~ TERM ]]
}

@test "join gate wait blocks until lock clears" {
  touch "${LOCK_FILE}"
  wait_log="${BATS_TEST_TMPDIR}/wait.log"

  "${BATS_CWD}/scripts/join_gate.sh" wait >"${wait_log}" 2>&1 &
  wait_pid=$!
  sleep 0.2
  kill -0 "${wait_pid}" >/dev/null 2>&1

  rm -f "${LOCK_FILE}"
  wait "${wait_pid}"
  status=$?
  [ "${status}" -eq 0 ]

  wait_output="$(cat "${wait_log}" 2>/dev/null)"
  [[ "${wait_output}" =~ outcome=blocked ]]
  [[ "${wait_output}" =~ outcome=ok ]]
}
