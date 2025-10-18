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

@test "pi_node_verifier --full emits text and JSON" {
  run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --full
  [ "$status" -eq 0 ]
  echo "$output" | grep "cloud_init:"
  json_line="$(printf '%s\n' "$output" | grep '"checks"')"
  [ -n "$json_line" ]
  JSON_LINE="$json_line" python - <<'PY'
import json
import os

json.loads(os.environ["JSON_LINE"])
PY
}

@test "pi_node_verifier marks HTTP checks as pass when endpoints respond" {
  port=$(python - <<'PY'
import socket
sock = socket.socket()
sock.bind(("", 0))
print(sock.getsockname()[1])
sock.close()
PY
  )

  python - <<'PY' "$port" &
import http.server
import socketserver
import sys

PORT = int(sys.argv[1])


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args, **kwargs):  # noqa: D401,N803,N802
        """Silence default request logging."""


with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
PY
  server_pid=$!
  sleep 1

  TOKEN_PLACE_HEALTH_URL="http://127.0.0.1:${port}/" \
    DSPACE_HEALTH_URL=skip \
    run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh"

  kill "$server_pid"
  wait "$server_pid" 2>/dev/null || true

  [ "$status" -eq 0 ]
  echo "$output" | grep "token_place_http: pass"
  echo "$output" | grep "dspace_http: skip"
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
  echo "$output" | grep "pi_home_repos: fail"
  echo "$output" | grep "token_place_http: fail"
  echo "$output" | grep "dspace_http: fail"
}

@test "pi_node_verifier reports pi_home_repos pass when repositories exist" {
  if [ -e /home/pi ]; then
    skip "/home/pi already exists"
  fi

  tmp="$(mktemp -d)"
  PATH="$tmp:$PATH"

  cat <<'EOF' > "$tmp/cloud-init"
#!/usr/bin/env bash
if [[ "$1" == "status" ]]; then
  exit 0
fi
echo "status: done"
exit 0
EOF
  chmod +x "$tmp/cloud-init"

  cat <<'EOF' > "$tmp/timedatectl"
#!/usr/bin/env bash
if [[ "$1" == "show" ]]; then
  echo "yes"
  exit 0
fi
exit 0
EOF
  chmod +x "$tmp/timedatectl"

  cat <<'EOF' > "$tmp/iptables"
#!/usr/bin/env bash
if [[ "$1" == "--version" ]]; then
  echo "iptables v1.8.7 (nf_tables)"
  exit 0
fi
exit 0
EOF
  chmod +x "$tmp/iptables"

  mkdir -p /home/pi/sugarkube/.git
  mkdir -p /home/pi/token.place/.git
  mkdir -p /home/pi/dspace/.git

  trap 'rm -rf /home/pi' RETURN

  TOKEN_PLACE_HEALTH_URL=skip \
    DSPACE_HEALTH_URL=skip \
    SKIP_COMPOSE=true \
    run "$BATS_TEST_DIRNAME/../scripts/pi_node_verifier.sh" --no-log

  [ "$status" -eq 0 ]
  echo "$output" | grep "pi_home_repos: pass"
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
