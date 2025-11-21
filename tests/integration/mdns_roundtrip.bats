#!/usr/bin/env bats

setup() {
  local helper_path
  helper_path="$(cd "$(dirname "${BATS_TEST_FILENAME}")/../fixtures/avahi_stub" && pwd)"/avahi_stub_helpers.bash

  if [ "${AVAHI_AVAILABLE:-0}" != "1" ] || ! command -v avahi-publish >/dev/null 2>&1; then
    # shellcheck source=tests/fixtures/avahi_stub/avahi_stub_helpers.bash
    . "${helper_path}"
    enable_avahi_stub
  fi

  if ! command -v avahi-publish >/dev/null 2>&1; then
    skip "avahi-publish not available even after enabling stub"
  fi

  if ! command -v avahi-browse >/dev/null 2>&1; then
    skip "avahi-browse not available even after enabling stub"
  fi

  if ! command -v avahi-resolve >/dev/null 2>&1; then
    skip "avahi-resolve not available even after enabling stub"
  fi

  publisher_pid=""
}

teardown() {
  if [ -n "${publisher_pid:-}" ]; then
    kill "${publisher_pid}" >/dev/null 2>&1 || true
    wait "${publisher_pid}" >/dev/null 2>&1 || true
    publisher_pid=""
  fi
}

@test "mdns self-check resolves a live avahi advertisement" {
  expected_host="$(hostname -f)"
  service_instance="k3s-test-it@${expected_host} (it)"
  service_type="_k3s-test-it._tcp"

  avahi-publish -s "${service_instance}" "${service_type}" 12345 \
    >"${BATS_TEST_TMPDIR}/avahi_publish.log" 2>&1 &
  publisher_pid=$!

  # Give avahi-publish a moment to announce the service before browsing.
  sleep 1

  run env \
    SUGARKUBE_CLUSTER=test \
    SUGARKUBE_ENV=it \
    SUGARKUBE_EXPECTED_HOST="${expected_host}" \
    SUGARKUBE_EXPECTED_ROLE=it \
    SUGARKUBE_SELFCHK_ATTEMPTS=10 \
    SUGARKUBE_SELFCHK_BACKOFF_START_MS=200 \
    SUGARKUBE_SELFCHK_BACKOFF_CAP_MS=1000 \
    "${BATS_CWD}/scripts/mdns_selfcheck.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ outcome=ok ]]
  expected_host_pattern="${expected_host//./\\.}"
  [[ "$output" =~ host=${expected_host_pattern} ]]
}
