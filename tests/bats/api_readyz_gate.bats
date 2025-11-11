#!/usr/bin/env bats

setup() {
  SERVER_PID=""
  ATTEMPT_FILE="${BATS_TEST_TMPDIR}/attempts"
}

teardown() {
  stop_readyz_server
}

find_free_port() {
  python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
print(port)
PY
}

start_readyz_server() {
  local port="$1"
  local responses_file="${2:-}"
  local cert="${BATS_TEST_TMPDIR}/server.crt"
  local key="${BATS_TEST_TMPDIR}/server.key"
  openssl req -x509 -nodes -newkey rsa:2048 \
    -subj '/CN=localhost' \
    -keyout "${key}" -out "${cert}" -days 1 >/dev/null 2>&1
  if [ -z "${responses_file}" ]; then
    responses_file="${BATS_TEST_TMPDIR}/readyz_responses.pydata"
    cat <<'EOF' >"${responses_file}"
[
    (503, "service unavailable"),
    (200, "[+]etcd failed\n"),
    (200, "[+]etcd ok\n[+]log ok\nreadyz check passed\n"),
]
EOF
  fi
  cat <<'PY' >"${BATS_TEST_TMPDIR}/ready_server.py"
import ast
import http.server
import os
import ssl
import sys
from pathlib import Path

attempts = 0
RESPONSES = []


def load_responses(responses_path: str) -> None:
    global RESPONSES
    text = Path(responses_path).read_text(encoding="utf-8")
    RESPONSES = ast.literal_eval(text)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        global attempts
        attempts += 1
        index = min(attempts - 1, len(RESPONSES) - 1)
        status, body = RESPONSES[index]
        if self.path.startswith("/readyz"):
            self.send_response(status)
            encoded = body.encode("utf-8")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        else:
            self.send_response(404)
            self.end_headers()
        Path(os.environ["ATTEMPT_FILE"]).write_text(str(attempts), encoding="utf-8")

    def log_message(self, *_args, **_kwargs):
        return


def main() -> None:
    port = int(sys.argv[1])
    cert = sys.argv[2]
    key = sys.argv[3]
    attempt_file = sys.argv[4]
    responses_path = sys.argv[5]
    os.environ["ATTEMPT_FILE"] = attempt_file
    load_responses(responses_path)
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
PY
  python3 "${BATS_TEST_TMPDIR}/ready_server.py" "${port}" "${cert}" "${key}" "${ATTEMPT_FILE}" "${responses_file}" &
  SERVER_PID=$!
  sleep 0.5
}

stop_readyz_server() {
  if [ -n "${SERVER_PID:-}" ]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
    SERVER_PID=""
  fi
}

@test "api ready gate waits for readyz ok" {
  local port
  port="$(find_free_port)"
  if [ -z "${port}" ]; then
    # TODO: Stabilize find_free_port so the test never bails on socket exhaustion.
    # Root cause: The helper occasionally returns nothing when the OS refuses to reserve a port.
    # Estimated fix: 30m to retry allocation or fall back to a deterministic testing range.
    skip "unable to allocate ephemeral port"
  fi
  start_readyz_server "${port}"

  run env \
    SERVER_HOST=localhost \
    SERVER_PORT="${port}" \
    SERVER_IP=127.0.0.1 \
    TIMEOUT=10 \
    POLL_INTERVAL=0.2 \
    "${BATS_CWD}/scripts/check_apiready.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=apiready ]]
  [[ "$output" =~ outcome=ok ]]
  [[ "$output" =~ attempts=3 ]]
  [ -f "${ATTEMPT_FILE}" ]
  [ "$(cat "${ATTEMPT_FILE}")" -eq 3 ]
}

@test "401 is treated as alive when ALLOW_HTTP_401=1" {
  local port
  port="$(find_free_port)"
  if [ -z "${port}" ]; then
    # TODO: Stabilize find_free_port so the test never bails on socket exhaustion.
    # Root cause: The helper occasionally returns nothing when the OS refuses to reserve a port.
    # Estimated fix: 30m to retry allocation or fall back to a deterministic testing range.
    skip "unable to allocate ephemeral port"
  fi

  local responses_file
  responses_file="${BATS_TEST_TMPDIR}/readyz_responses_401.pydata"
  cat <<'EOF' >"${responses_file}"
[
    (401, "auth required"),
    (200, "readyz check passed\n"),
]
EOF
  start_readyz_server "${port}" "${responses_file}"

  run env \
    ALLOW_HTTP_401=1 \
    SERVER_HOST=localhost \
    SERVER_PORT="${port}" \
    SERVER_IP=127.0.0.1 \
    TIMEOUT=5 \
    POLL_INTERVAL=0.2 \
    "${BATS_CWD}/scripts/check_apiready.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=apiready ]]
  [[ "$output" =~ outcome=alive ]]
  [[ "$output" =~ mode=alive ]]
  [[ "$output" =~ status=401 ]]
  [[ "$output" =~ attempts=1 ]]
  [ -f "${ATTEMPT_FILE}" ]
  [ "$(cat "${ATTEMPT_FILE}")" -eq 1 ]

  stop_readyz_server
  rm -f "${ATTEMPT_FILE}"

  local port_fail
  port_fail="$(find_free_port)"
  if [ -z "${port_fail}" ]; then
    # TODO: Stabilize find_free_port so the test never bails on socket exhaustion.
    # Root cause: The helper occasionally returns nothing when the OS refuses to reserve a port.
    # Estimated fix: 30m to retry allocation or fall back to a deterministic testing range.
    skip "unable to allocate ephemeral port for failure case"
  fi

  local responses_fail
  responses_fail="${BATS_TEST_TMPDIR}/readyz_responses_401_only.pydata"
  cat <<'EOF' >"${responses_fail}"
[
    (401, "auth required"),
]
EOF
  start_readyz_server "${port_fail}" "${responses_fail}"

  run env \
    SERVER_HOST=localhost \
    SERVER_PORT="${port_fail}" \
    SERVER_IP=127.0.0.1 \
    TIMEOUT=3 \
    POLL_INTERVAL=0.2 \
    "${BATS_CWD}/scripts/check_apiready.sh"

  [ "$status" -ne 0 ]
  [[ "$output" =~ event=apiready ]]
  [[ "$output" =~ outcome=timeout ]]
  [[ "$output" =~ last_status="401:0" ]]
}
