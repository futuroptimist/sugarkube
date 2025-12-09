#!/usr/bin/env bats

load helpers/path_stub

bats_require_minimum_version 1.5.0

setup() {
  setup_path_stub_dir
}

@test "mdns_diag stub mode short-circuits local checks" {
  run env \
    MDNS_DIAG_STUB_MODE=1 \
    MDNS_DIAG_HOSTNAME=stub.local \
    SUGARKUBE_CLUSTER=ci \
    SUGARKUBE_ENV=stub \
    "${BATS_CWD}/scripts/mdns_diag.sh" --service-type "_k3s-ci-stub._tcp"

  [ "$status" -eq 0 ]
  [[ "$output" =~ "=== mDNS Diagnostic ===" ]]
  [[ "$output" =~ "Hostname: stub.local" ]]
  [[ "$output" =~ "Service:  _k3s-ci-stub._tcp" ]]
  [[ "$output" =~ "Stub mode enabled; skipping Avahi and NSS checks." ]]
  [[ "$output" =~ "Unset MDNS_DIAG_STUB_MODE to run full diagnostics." ]]
}
