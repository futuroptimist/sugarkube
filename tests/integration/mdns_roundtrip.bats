#!/usr/bin/env bats

setup() {
  if [ "${AVAHI_AVAILABLE:-0}" != "1" ]; then
    # TODO: Provide a hermetic Avahi fixture so this suite runs without AVAHI_AVAILABLE=1.
    # Root cause: The integration exercise still depends on a host Avahi daemon toggle.
    # Estimated fix: 60m to bundle a containerised Avahi helper or dedicated stub binaries.
    skip "AVAHI_AVAILABLE not enabled"
  fi

  if ! command -v avahi-publish >/dev/null 2>&1; then
    # TODO: Ship avahi-publish alongside the mdns_roundtrip fixtures for local runs.
    # Root cause: Developers without avahi-utils cannot advertise services during the test.
    # Estimated fix: 20m to install avahi-utils or extend the stub harness in tests/fixtures.
    skip "avahi-publish not available"
  fi

  if ! command -v avahi-browse >/dev/null 2>&1; then
    # TODO: Package avahi-browse for the integration harness to browse advertised services.
    # Root cause: The suite shells out to avahi-browse, which is missing on minimal installs.
    # Estimated fix: 20m to include avahi-utils in docs or provide a bats stub.
    skip "avahi-browse not available"
  fi

  if ! command -v avahi-resolve >/dev/null 2>&1; then
    # TODO: Ensure avahi-resolve is present so the resolver path exercises real binaries.
    # Root cause: The integration test still shells to avahi-resolve to confirm hostnames.
    # Estimated fix: 20m to install avahi-utils or extend mdns fixtures with a resolver stub.
    skip "avahi-resolve not available"
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
