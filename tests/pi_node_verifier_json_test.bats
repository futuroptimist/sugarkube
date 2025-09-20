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

  cat <<'EOF' > "$tmp/kubectl"
#!/usr/bin/env bash
if [[ "$1" == "--kubeconfig" ]]; then
  shift 2
fi
if [[ "$1" == "get" && "$2" == "nodes" ]]; then
  echo "pi NotReady control-plane 5m v1.29.0"
  exit 0
fi
exit 1
EOF
  chmod +x "$tmp/kubectl"

  cat <<'EOF' > "$tmp/systemctl"
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 3
fi
exit 1
EOF
  chmod +x "$tmp/systemctl"

  cat <<'EOF' > "$tmp/curl"
#!/usr/bin/env bash
exit 22
EOF
  chmod +x "$tmp/curl"

  cat <<'EOF' > "$tmp/wget"
#!/usr/bin/env bash
exit 4
EOF
  chmod +x "$tmp/wget"

  touch "$tmp/kubeconfig"
  export KUBECONFIG="$tmp/kubeconfig"

  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --json
  [ "$status" -eq 0 ]
  echo "$output" | jq -e '.checks[] | select(.name=="cloud_init") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="time_sync") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="iptables_backend") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="k3s_node_ready") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="projects_compose_active") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="token_place_http") | .status=="fail"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="dspace_http") | .status=="fail"' > /dev/null
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
  echo "$output" | jq -e '.checks[] | select(.name=="k3s_node_ready") | .status=="skip"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="projects_compose_active") | .status=="skip"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="token_place_http") | .status=="skip"' > /dev/null
  echo "$output" | jq -e '.checks[] | select(.name=="dspace_http") | .status=="skip"' > /dev/null
}
