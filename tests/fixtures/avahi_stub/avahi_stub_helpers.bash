#!/usr/bin/env bash
# Helper to activate hermetic Avahi CLI stubs for integration tests.

enable_avahi_stub() {
  local fixture_root
  fixture_root="$(cd "$(dirname "${BATS_TEST_FILENAME:-$0}")/../fixtures/avahi_stub" && pwd)"

  export AVAHI_STUB_DIR="${BATS_TEST_TMPDIR:-/tmp}/avahi_stub"
  export AVAHI_STUB_HOST="${SUGARKUBE_EXPECTED_HOST:-$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo localhost.local)}"
  export AVAHI_STUB_IPV4="${SUGARKUBE_EXPECTED_IPV4:-127.0.0.1}"
  export PATH="${fixture_root}:${PATH}"
  export AVAHI_AVAILABLE=1
}
