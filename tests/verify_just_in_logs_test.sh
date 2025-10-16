#!/usr/bin/env bash
# Validate scripts/verify_just_in_logs.sh against aggregate and per-stage log layouts.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${ROOT_DIR}/scripts/verify_just_in_logs.sh"

if [ ! -x "${SCRIPT}" ]; then
  echo "verify_just_in_logs.sh missing or not executable" >&2
  exit 1
fi

run_success_case() {
  local fixture_name="$1"
  local fixture_dir="${ROOT_DIR}/tests/fixtures/${fixture_name}/deploy"
  local output
  if ! output=$(bash "${SCRIPT}" "${fixture_dir}" 2>&1); then
    echo "expected ${fixture_name} to succeed" >&2
    echo "--- output ---" >&2
    echo "${output}" >&2
    exit 1
  fi
  if ! grep -Fq '[sugarkube] just version:' <<<"${output}"; then
    echo "missing just version line in ${fixture_name} output" >&2
    echo "--- output ---" >&2
    echo "${output}" >&2
    exit 1
  fi
}

run_failure_case() {
  local fixture_name="$1"
  local fixture_dir="${ROOT_DIR}/tests/fixtures/${fixture_name}/deploy"
  local output
  set +e
  output=$(bash "${SCRIPT}" "${fixture_dir}" 2>&1)
  status=$?
  set -e
  if [ "${status}" -eq 0 ]; then
    echo "expected ${fixture_name} to fail" >&2
    echo "--- output ---" >&2
    echo "${output}" >&2
    exit 1
  fi
  if [ "${status}" -ne 1 ]; then
    echo "expected exit code 1 for ${fixture_name}, got ${status}" >&2
    echo "--- output ---" >&2
    echo "${output}" >&2
    exit 1
  fi
  if ! grep -Fq 'grep just summary' <<<"${output}"; then
    echo "missing grep summary in ${fixture_name} output" >&2
    echo "--- output ---" >&2
    echo "${output}" >&2
    exit 1
  fi
}

run_success_case "logs-aggregate"
run_success_case "logs-stage"
run_failure_case "logs-missing"

echo "verify_just_in_logs tests passed"
