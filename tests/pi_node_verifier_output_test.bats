#!/usr/bin/env bats

@test "pi_node_verifier prints human-readable checks" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh"
  [ "$status" -eq 0 ]
  echo "$output" | grep "cgroup_memory:"
  echo "$output" | grep "cloud_init:"
  echo "$output" | grep "time_sync:"
  echo "$output" | grep "iptables_backend:"
  echo "$output" | grep "k3s_check_config:"
  echo "$output" | grep "k3s_node_ready:"
  echo "$output" | grep "projects_compose_active:"
  echo "$output" | grep "token_place_http:"
  echo "$output" | grep "dspace_http:"
}

@test "pi_node_verifier reports failing checks" {
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

  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh"
  [ "$status" -eq 0 ]
  echo "$output" | grep "cloud_init: fail"
  echo "$output" | grep "time_sync: fail"
  echo "$output" | grep "iptables_backend: fail"
  echo "$output" | grep "k3s_node_ready: fail"
  echo "$output" | grep "projects_compose_active: fail"
  echo "$output" | grep "token_place_http: fail"
  echo "$output" | grep "dspace_http: fail"
}

@test "pi_node_verifier --help shows usage" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == Usage:* ]]
  [[ "$output" == *"--json"* ]]
}

@test "pi_node_verifier rejects unknown options" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --bad-flag
  [ "$status" -eq 1 ]
  echo "$output" | grep "Unknown option: --bad-flag"
  echo "$output" | grep "Usage:"
}
