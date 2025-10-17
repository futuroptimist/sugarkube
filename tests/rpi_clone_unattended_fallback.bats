#!/usr/bin/env bats

setup() {
  export SKIP_CLONE_TO_NVME_MAIN=1
  TEST_BIN_DIR="$(mktemp -d)"
  PATH="${TEST_BIN_DIR}:$PATH"
  export PATH TEST_BIN_DIR
  RPI_CLONE_STATE="${BATS_TEST_TMPDIR}/rpi_clone_state"
  RPI_CLONE_CALLS="${BATS_TEST_TMPDIR}/rpi_clone_calls.log"
  export RPI_CLONE_STATE RPI_CLONE_CALLS
  cat <<'STUB' > "${TEST_BIN_DIR}/rpi-clone"
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${RPI_CLONE_CALLS}"
if [[ ! -f "${RPI_CLONE_STATE}" ]]; then
  touch "${RPI_CLONE_STATE}"
  echo "Unattended -u option not allowed when initializing" >&2
  exit 1
fi
exit 0
STUB
  chmod +x "${TEST_BIN_DIR}/rpi-clone"
  # shellcheck disable=SC1091
  source "$BATS_TEST_DIRNAME/../scripts/clone_to_nvme.sh"
}

teardown() {
  if [[ -d "${TEST_BIN_DIR:-}" ]]; then
    rm -rf "${TEST_BIN_DIR}"
  fi
  rm -f "${RPI_CLONE_STATE:-}" "${RPI_CLONE_CALLS:-}"
  unset SKIP_CLONE_TO_NVME_MAIN
}

@test "Fallback retries with -U when unattended init fails" {
  run run_rpi_clone_with_fallback "/dev/testdisk"
  [ "$status" -eq 0 ]
  mapfile -t calls < "${RPI_CLONE_CALLS}"
  [ "${#calls[@]}" -eq 2 ]
  [[ "${calls[0]}" == *"-u /dev/testdisk" ]]
  [[ "${calls[1]}" == *"-U /dev/testdisk" ]]
}
