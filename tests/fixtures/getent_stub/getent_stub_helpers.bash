#!/usr/bin/env bash
# Helper to activate a hermetic getent stub for integration tests.

enable_getent_stub() {
  local fixture_root
  fixture_root="$(cd "$(dirname "${BATS_TEST_FILENAME:-$0}")/../fixtures/getent_stub" && pwd)"

  export GETENT_STUB_HOST="${SUGARKUBE_EXPECTED_HOST:-${EXPECTED_HOST:-localhost.local}}"
  export GETENT_STUB_IPV4="${SUGARKUBE_EXPECTED_IPV4:-${EXPECTED_IPV4:-127.0.0.1}}"

  export PATH="${fixture_root}:${PATH}"
}
