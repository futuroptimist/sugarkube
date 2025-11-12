#!/usr/bin/env bats

@test "pi_node_verifier skips missing tools" {
  tmp="$(mktemp -d)"
  ln -s "$(command -v bash)" "$tmp/bash"
  ln -s "$(command -v grep)" "$tmp/grep"
  PATH="$tmp" run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh"
  [ "$status" -eq 0 ]
  echo "$output" | grep "cloud_init: skip"
  echo "$output" | grep "time_sync: skip"
  echo "$output" | grep "kube_proxy_dataplane: skip"
  echo "$output" | grep "k3s_check_config: skip"
  echo "$output" | grep "k3s_node_ready: skip"
  echo "$output" | grep "projects_compose_active: skip"
  echo "$output" | grep "token_place_http: skip"
  echo "$output" | grep "dspace_http: skip"
}

@test "pi_node_verifier --skip-compose toggles the compose check" {
  tmp="$(mktemp -d)"
  log="$tmp/systemctl.log"
  cat <<EOF >"$tmp/systemctl"
#!/usr/bin/env bash
echo "called" >>"$log"
exit 3
EOF
  chmod +x "$tmp/systemctl"

  old_path="$PATH"
  PATH="$tmp:$PATH" run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --skip-compose
  [ "$status" -eq 0 ]
  [ ! -f "$log" ]
  echo "$output" | grep "projects_compose_active: skip"

  rm -f "$log"
  PATH="$tmp:$old_path" run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --skip-compose=false
  [ "$status" -eq 0 ]
  [ -f "$log" ]
  echo "$output" | grep "projects_compose_active: fail"

  PATH="$old_path"
}
