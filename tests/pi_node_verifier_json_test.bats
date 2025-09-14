#!/usr/bin/env bats

@test "pi_node_verifier emits valid JSON" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --json
  [ "$status" -eq 0 ]
  echo "$output" | jq -e '.checks | length > 0' > /dev/null
}

@test "pi_node_verifier reports failing checks in JSON" {
  tmp="$(mktemp -d)"
  PATH="$tmp:$PATH"

  cat <<'EOF' > "$tmp/cloud-init"
#!/usr/bin/env bash
exit 1
EOF
  chmod +x "$tmp/cloud-init"

  cat <<'EOF' > "$tmp/timedatectl"
#!/usr/bin/env bash
echo "NTPSynchronized=no"
exit 0
EOF
  chmod +x "$tmp/timedatectl"

  cat <<'EOF' > "$tmp/iptables"
#!/usr/bin/env bash
echo "iptables v1.8.7 (legacy)"
exit 0
EOF
  chmod +x "$tmp/iptables"

  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --json
  [ "$status" -eq 0 ]
  echo "$output" | jq -e '.checks[] | select(.name=="cloud_init") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="time_sync") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="iptables_backend") | .status=="fail"' > /dev/null
}

@test "pi_node_verifier reports skipped checks in JSON" {
  tmp="$(mktemp -d)"
  ln -s "$(command -v bash)" "$tmp/bash"
  ln -s "$(command -v grep)" "$tmp/grep"
  ln -s "$(command -v jq)" "$tmp/jq"
  PATH="$tmp" run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --json
  [ "$status" -eq 0 ]
  echo "$output" | jq -e '.checks[] | select(.name=="cloud_init") | .status=="skip"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="time_sync") | .status=="skip"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="iptables_backend") | .status=="skip"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="k3s_check_config") | .status=="skip"' > /dev/null
}
