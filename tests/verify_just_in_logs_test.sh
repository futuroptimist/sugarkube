#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
VERIFY_SCRIPT="${REPO_ROOT}/scripts/verify_just_in_logs.sh"

run_positive_fixture() {
  local fixture=$1
  echo "--- running positive fixture: ${fixture} ---"
  if ! (cd "${REPO_ROOT}/tests/fixtures/${fixture}" && bash "${VERIFY_SCRIPT}" deploy); then
    echo "Expected success for fixture ${fixture}" >&2
    exit 1
  fi
}

echo "[verify-just] ensuring script handles aggregate logs"
run_positive_fixture "logs-aggregate"

echo "[verify-just] ensuring script handles stage logs"
run_positive_fixture "logs-stage"

echo "--- running negative fixture: logs-missing ---"
if (cd "${REPO_ROOT}/tests/fixtures/logs-missing" && bash "${VERIFY_SCRIPT}" deploy); then
  echo "Expected failure for fixture logs-missing" >&2
  exit 1
fi

echo "All verify_just_in_logs fixtures behaved as expected."
