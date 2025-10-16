#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script_path="${repo_root}/scripts/verify_just_in_logs.sh"
fixtures_root="${repo_root}/tests/fixtures"

run_success() {
  local fixture=$1
  local deploy_dir="${fixtures_root}/${fixture}/deploy"
  echo "[test] expecting success for ${fixture}"
  if ! bash "${script_path}" "${deploy_dir}" >/dev/null; then
    echo "[fail] ${fixture} should succeed" >&2
    exit 1
  fi
  echo "[pass] ${fixture} succeeded"
}

run_failure() {
  local fixture=$1
  local deploy_dir="${fixtures_root}/${fixture}/deploy"
  echo "[test] expecting failure for ${fixture}"
  if bash "${script_path}" "${deploy_dir}" >/dev/null; then
    echo "[fail] ${fixture} should have failed" >&2
    exit 1
  else
    local status=$?
    if [ "${status}" -ne 1 ]; then
      echo "[fail] ${fixture} exited with ${status}, expected 1" >&2
      exit 1
    fi
  fi
  echo "[pass] ${fixture} failed as expected"
}

run_success "logs-aggregate"
run_success "logs-stage"
run_failure "logs-missing"

echo "verify_just_in_logs_test: all scenarios covered"
