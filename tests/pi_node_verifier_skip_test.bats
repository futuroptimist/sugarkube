#!/usr/bin/env bats

@test "pi_node_verifier skips missing tools" {
  tmp="$(mktemp -d)"
  ln -s "$(command -v bash)" "$tmp/bash"
  ln -s "$(command -v grep)" "$tmp/grep"
  PATH="$tmp" run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh"
  [ "$status" -eq 0 ]
  echo "$output" | grep "cloud_init: skip"
  echo "$output" | grep "time_sync: skip"
  echo "$output" | grep "iptables_backend: skip"
  echo "$output" | grep "k3s_check_config: skip"
  echo "$output" | grep "k3s_node_ready: skip"
  echo "$output" | grep "projects_compose_active: skip"
  echo "$output" | grep "token_place_http: skip"
  echo "$output" | grep "dspace_http: skip"
}
