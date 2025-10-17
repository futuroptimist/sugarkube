#!/usr/bin/env bash
# Purpose: Orchestrate spot-check, boot-order alignment, clone, and reboot migration flow.
# Usage: sudo ./scripts/migrate_to_nvme.sh
set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)

MIGRATE_ARTIFACTS=${MIGRATE_ARTIFACTS:-"${REPO_ROOT}/artifacts/migrate-to-nvme"}
SPOT_CHECK_CMD=${SPOT_CHECK_CMD:-"${SCRIPT_DIR}/spot_check.sh"}
SPOT_CHECK_ARGS=${SPOT_CHECK_ARGS:-}
EEPROM_CMD=${EEPROM_CMD:-"${SCRIPT_DIR}/eeprom_nvme_first.sh"}
EEPROM_ARGS=${EEPROM_ARGS:-}
CLONE_CMD=${CLONE_CMD:-"${SCRIPT_DIR}/clone_to_nvme.sh"}
CLONE_ARGS=${CLONE_ARGS:-}
CLONE_TARGET=${TARGET:-${CLONE_TARGET:-}}
CLONE_WIPE=${WIPE:-${CLONE_WIPE:-0}}
SKIP_EEPROM=${SKIP_EEPROM:-0}
NO_REBOOT=${NO_REBOOT:-0}

mkdir -p "${MIGRATE_ARTIFACTS}"
LOG_FILE="${MIGRATE_ARTIFACTS}/migrate.log"
: >"${LOG_FILE}"
exec > >(tee "${LOG_FILE}") 2>&1

run_step() {
  local label=$1
  shift
  printf '[migrate] >>> %s\n' "${label}"
  "$@"
}

if [[ ${EUID:-0} -ne 0 ]]; then
  if [[ "${ALLOW_NON_ROOT:-0}" == "1" ]]; then
    printf '[migrate] ALLOW_NON_ROOT=1 set; continuing without sudo re-exec\n'
  elif command -v sudo >/dev/null 2>&1; then
    exec sudo \
      MIGRATE_ARTIFACTS="${MIGRATE_ARTIFACTS}" \
      SPOT_CHECK_CMD="${SPOT_CHECK_CMD}" \
      SPOT_CHECK_ARGS="${SPOT_CHECK_ARGS}" \
      EEPROM_CMD="${EEPROM_CMD}" \
      EEPROM_ARGS="${EEPROM_ARGS}" \
      CLONE_CMD="${CLONE_CMD}" \
      CLONE_ARGS="${CLONE_ARGS}" \
      TARGET="${CLONE_TARGET}" \
      WIPE="${CLONE_WIPE}" \
      SKIP_EEPROM="${SKIP_EEPROM}" \
      NO_REBOOT="${NO_REBOOT}" \
      "$0" "$@"
  else
    echo "This script requires root privileges." >&2
    exit 1
  fi
fi

run_step spot-check "${SPOT_CHECK_CMD}" ${SPOT_CHECK_ARGS}

if [[ "${SKIP_EEPROM}" != "1" ]]; then
  run_step eeprom "${EEPROM_CMD}" ${EEPROM_ARGS}
else
  printf '[migrate] SKIP_EEPROM=1, skipping EEPROM update\n'
fi

run_step clone env TARGET="${CLONE_TARGET}" WIPE="${CLONE_WIPE}" "${CLONE_CMD}" ${CLONE_ARGS}

if [[ "${NO_REBOOT}" != "1" ]]; then
  printf '[migrate] Rebooting to complete migration\n'
  sync
  reboot
else
  printf '[migrate] NO_REBOOT=1 set; not rebooting automatically\n'
fi

printf '[migrate] Log captured at %s\n' "${LOG_FILE}"
