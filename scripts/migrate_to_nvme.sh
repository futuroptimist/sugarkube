#!/usr/bin/env bash
# Chain the Raspberry Pi spot-check, EEPROM alignment, clone, and reboot steps.
# Designed to run on-device after flashing a new image.
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

SPOT_CHECK_CMD=${SPOT_CHECK_CMD:-"${SCRIPT_DIR}/spot_check.sh"}
SPOT_CHECK_ARGS=${SPOT_CHECK_ARGS:-}
EEPROM_CMD=${EEPROM_CMD:-"${SCRIPT_DIR}/eeprom_nvme_first.sh"}
EEPROM_ARGS=${EEPROM_ARGS:-}
CLONE_CMD=${CLONE_CMD:-"${SCRIPT_DIR}/clone_to_nvme.sh"}
CLONE_ARGS=${CLONE_ARGS:-}
MIGRATE_ARTIFACTS=${MIGRATE_ARTIFACTS:-"${REPO_ROOT}/artifacts/migrate-to-nvme"}
SKIP_EEPROM=${SKIP_EEPROM:-0}
NO_REBOOT=${NO_REBOOT:-0}
CLONE_TARGET=${CLONE_TARGET:-${TARGET:-}}
CLONE_WIPE=${CLONE_WIPE:-${WIPE:-}}

mkdir -p "${MIGRATE_ARTIFACTS}"
LOG_FILE="${MIGRATE_ARTIFACTS}/migrate.log"

parse_args() {
  local raw=$1
  if [[ -z "${raw}" ]]; then
    echo ""
    return
  fi
  # shellcheck disable=SC2206  # Intentional word splitting to honour CLI-style args.
  local -a parts=( ${raw} )
  printf '%s\n' "${parts[@]}"
}

readarray -t SPOT_CHECK_ARRAY < <(parse_args "${SPOT_CHECK_ARGS}") || true
readarray -t EEPROM_ARRAY < <(parse_args "${EEPROM_ARGS}") || true
readarray -t CLONE_ARRAY < <(parse_args "${CLONE_ARGS}") || true

run_step() {
  local label=$1
  shift
  printf '[migrate] >>> %s\n' "${label}"
  "$@"
}

clone_step() {
  local -a env_vars=()
  if [[ -n "${CLONE_TARGET}" ]]; then
    env_vars+=("TARGET=${CLONE_TARGET}")
  fi
  if [[ -n "${CLONE_WIPE}" ]]; then
    env_vars+=("WIPE=${CLONE_WIPE}")
  fi
  if (( ${#env_vars[@]} > 0 )); then
    env "${env_vars[@]}" "${CLONE_CMD}" "${CLONE_ARRAY[@]}"
  else
    "${CLONE_CMD}" "${CLONE_ARRAY[@]}"
  fi
}

main() {
  run_step spot-check "${SPOT_CHECK_CMD}" "${SPOT_CHECK_ARRAY[@]}"
  if [[ "${SKIP_EEPROM}" != "1" ]]; then
    run_step eeprom "${EEPROM_CMD}" "${EEPROM_ARRAY[@]}"
  else
    printf '[migrate] SKIP_EEPROM=1, skipping EEPROM update\n'
  fi
  run_step clone clone_step
  if [[ "${NO_REBOOT}" != "1" ]]; then
    printf '[migrate] Rebooting to complete migration\n'
    sync
    reboot
  else
    printf '[migrate] NO_REBOOT=1 set; not rebooting automatically\n'
  fi
  printf '[migrate] Log captured at %s\n' "${LOG_FILE}"
}

main "$@" | tee "${LOG_FILE}"
exit_code=${PIPESTATUS[0]}
exit "${exit_code}"
