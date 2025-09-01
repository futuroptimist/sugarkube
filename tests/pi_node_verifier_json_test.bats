#!/usr/bin/env bats

@test "pi_node_verifier emits valid JSON" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --json
  [ "$status" -eq 0 ]
  echo "$output" | jq -e '.checks | length > 0' > /dev/null
}
