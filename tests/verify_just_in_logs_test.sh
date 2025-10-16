#!/usr/bin/env bash
# Validate scripts/verify_just_in_logs.sh against positive and negative fixtures.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/verify_just_in_logs.sh"
FIXTURES_DIR="${ROOT_DIR}/tests/fixtures"

if [ ! -x "${SCRIPT}" ]; then
  echo "verify_just_in_logs.sh missing or not executable" >&2
  exit 1
fi

run_expect_success() {
  local label="$1"
  local fixture_dir="$2"
  echo "--- ${label} ---"
  if ! bash "${SCRIPT}" "${fixture_dir}/deploy"; then
    echo "Expected success for ${label}" >&2
    exit 1
  fi
}

run_expect_failure() {
  local label="$1"
  local fixture_dir="$2"
  echo "--- ${label} ---"
  set +e
  bash "${SCRIPT}" "${fixture_dir}/deploy"
  status=$?
  set -e
  if [ "${status}" -ne 1 ]; then
    echo "Expected failure exit code 1 for ${label}, got ${status}" >&2
    exit 1
  fi
}

run_expect_success "aggregate log fixture" "${FIXTURES_DIR}/logs-aggregate"
run_expect_success "stage log fixture" "${FIXTURES_DIR}/logs-stage"
run_expect_failure "missing marker fixture" "${FIXTURES_DIR}/logs-missing"

echo "verify_just_in_logs tests passed"
