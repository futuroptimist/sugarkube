#!/usr/bin/env bats

setup() {
  cd "${BATS_TEST_DIRNAME}/.."
  export TEST_BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "${TEST_BIN}"
  export PATH="${TEST_BIN}:$PATH"
  export MIGRATE_CALL_LOG="${BATS_TEST_TMPDIR}/migrate_calls.log"
  : >"${MIGRATE_CALL_LOG}"
  export ALLOW_NON_ROOT=1

  cat >"${TEST_BIN}/spot-check" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "spot-check:$*" >>"${MIGRATE_CALL_LOG}"
STUB
  chmod +x "${TEST_BIN}/spot-check"

  cat >"${TEST_BIN}/eeprom" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "eeprom:$*" >>"${MIGRATE_CALL_LOG}"
STUB
  chmod +x "${TEST_BIN}/eeprom"

  cat >"${TEST_BIN}/clone" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${TARGET:-}" != "/dev/testdisk" ]]; then
  echo "TARGET not forwarded" >&2
  exit 1
fi
if [[ "${WIPE:-}" != "1" ]]; then
  echo "WIPE not forwarded" >&2
  exit 1
fi
echo "clone:$*" >>"${MIGRATE_CALL_LOG}"
STUB
  chmod +x "${TEST_BIN}/clone"

  cat >"${TEST_BIN}/reboot" <<'STUB'
#!/usr/bin/env bash
set -Eeuo pipefail
echo "reboot:$*" >>"${MIGRATE_CALL_LOG}"
STUB
  chmod +x "${TEST_BIN}/reboot"
}

@test "migrate_to_nvme runs all steps" {
  export MIGRATE_ARTIFACTS="${BATS_TEST_TMPDIR}/artifacts"
  export SPOT_CHECK_CMD="${TEST_BIN}/spot-check"
  export EEPROM_CMD="${TEST_BIN}/eeprom"
  export CLONE_CMD="${TEST_BIN}/clone"
  export TARGET="/dev/testdisk"
  export WIPE=1
  run scripts/migrate_to_nvme.sh
  [ "$status" -eq 0 ]
  [[ "$output" == *"[migrate] >>> spot-check"* ]]
  [[ "$output" == *"[migrate] >>> eeprom"* ]]
  [[ "$output" == *"[migrate] >>> clone"* ]]
  [[ "$output" == *"[migrate] Rebooting to complete migration"* ]]

  [ -f "${MIGRATE_ARTIFACTS}/migrate.log" ]
  mapfile -t calls <"${MIGRATE_CALL_LOG}"
  [ "${#calls[@]}" -eq 4 ]
  [[ "${calls[0]}" == "spot-check:"* ]]
  [[ "${calls[1]}" == "eeprom:"* ]]
  [[ "${calls[2]}" == "clone:"* ]]
  [[ "${calls[3]}" == "reboot:"* ]]
}

@test "migrate_to_nvme honors SKIP_EEPROM and NO_REBOOT" {
  export MIGRATE_ARTIFACTS="${BATS_TEST_TMPDIR}/artifacts2"
  export SPOT_CHECK_CMD="${TEST_BIN}/spot-check"
  export EEPROM_CMD="${TEST_BIN}/eeprom"
  export CLONE_CMD="${TEST_BIN}/clone"
  export TARGET="/dev/testdisk"
  export WIPE=1
  export SKIP_EEPROM=1
  export NO_REBOOT=1
  run scripts/migrate_to_nvme.sh
  [ "$status" -eq 0 ]
  [[ "$output" == *"SKIP_EEPROM=1"* ]]
  [[ "$output" == *"NO_REBOOT=1 set"* ]]

  mapfile -t calls <"${MIGRATE_CALL_LOG}"
  [ "${#calls[@]}" -eq 2 ]
  [[ "${calls[0]}" == "spot-check:"* ]]
  [[ "${calls[1]}" == "clone:"* ]]
}
