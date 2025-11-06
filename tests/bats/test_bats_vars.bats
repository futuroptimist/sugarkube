#!/usr/bin/env bats

@test "check BATS variables from actual test location" {
  echo "BATS_TEST_DIRNAME=$BATS_TEST_DIRNAME"
  echo "BATS_TEST_FILENAME=$BATS_TEST_FILENAME"
  echo "PWD=$PWD"
  # Check if parent directory works
  repo_root="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  echo "Calculated repo root=$repo_root"
  [ -f "${repo_root}/scripts/lib/summary.sh" ]
}
