#!/usr/bin/env bats

@test "pi_node_verifier exits on corrupted JSON" {
  PI_NODE_VERIFIER_CORRUPT_JSON=1 run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --json
  [ "$status" -ne 0 ]
  [[ "$output" =~ "Invalid JSON" ]]
}
