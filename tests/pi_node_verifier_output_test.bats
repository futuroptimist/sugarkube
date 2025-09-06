#!/usr/bin/env bats

@test "pi_node_verifier prints human-readable checks" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh"
  [ "$status" -eq 0 ]
  echo "$output" | grep "cgroup_memory:"
  echo "$output" | grep "cloud_init:"
  echo "$output" | grep "time_sync:"
  echo "$output" | grep "iptables_backend:"
  echo "$output" | grep "k3s_check_config:"
}

@test "pi_node_verifier --help shows usage" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == Usage:* ]]
  [[ "$output" == *"--json"* ]]
}
