#!/usr/bin/env bats

setup() {
  SERVER_PID=""
  ATTEMPT_FILE="${BATS_TEST_TMPDIR}/attempts"
}

teardown() {
  if [ -n "${SERVER_PID:-}" ]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
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
  local responses_override="${2:-}"
  local cert="${BATS_TEST_TMPDIR}/server.crt"
  local key="${BATS_TEST_TMPDIR}/server.key"
  openssl req -x509 -nodes -newkey rsa:2048 \
    -subj '/CN=localhost' \
    -keyout "${key}" -out "${cert}" -days 1 >/dev/null 2>&1
  cat <<'PY' >"${BATS_TEST_TMPDIR}/ready_server.py"
import ast
import http.server
import os
import ssl
import sys
from pathlib import Path

DEFAULT_RESPONSES = [
    (503, "service unavailable"),
    (200, "[+]etcd failed\n"),
    (200, "[+]etcd ok\n[+]log ok\nreadyz check passed\n"),
]

raw_override = os.environ.get("READYZ_RESPONSES_OVERRIDE", "")
if raw_override:
    try:
        parsed = ast.literal_eval(raw_override)
        RESPONSES = [(int(code), str(body)) for code, body in parsed]
    except Exception:  # pragma: no cover - defensive fallback
        RESPONSES = DEFAULT_RESPONSES
else:
    RESPONSES = DEFAULT_RESPONSES

attempts = 0

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
    os.environ["ATTEMPT_FILE"] = attempt_file
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
PY
  if [ -n "${responses_override}" ]; then
    READYZ_RESPONSES_OVERRIDE="${responses_override}" \
      python3 "${BATS_TEST_TMPDIR}/ready_server.py" "${port}" "${cert}" "${key}" "${ATTEMPT_FILE}" &
  else
    python3 "${BATS_TEST_TMPDIR}/ready_server.py" "${port}" "${cert}" "${key}" "${ATTEMPT_FILE}" &
  fi
  SERVER_PID=$!
  sleep 0.5
}

reset_readyz_attempts() {
  : >"${ATTEMPT_FILE}"
}

@test "api ready gate waits for readyz ok" {
  local port
  port="$(find_free_port)"
  if [ -z "${port}" ]; then
    skip "unable to allocate ephemeral port"
  fi
  start_readyz_server "${port}"
  reset_readyz_attempts

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
  local responses
  responses="$(python3 - <<'PY'
import json
print(json.dumps([(401, "auth required"), (200, "readyz check passed\n")]))
PY
)"

  local port
  port="$(find_free_port)"
  if [ -z "${port}" ]; then
    skip "unable to allocate ephemeral port"
  fi
  start_readyz_server "${port}" "${responses}"
  reset_readyz_attempts

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
  [ -f "${ATTEMPT_FILE}" ]
  [ "$(cat "${ATTEMPT_FILE}")" -eq 1 ]

  if [ -n "${SERVER_PID:-}" ]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
    SERVER_PID=""
  fi

  port="$(find_free_port)"
  if [ -z "${port}" ]; then
    skip "unable to allocate ephemeral port"
  fi
  start_readyz_server "${port}" "${responses}"
  reset_readyz_attempts

  run env \
    SERVER_HOST=localhost \
    SERVER_PORT="${port}" \
    SERVER_IP=127.0.0.1 \
    TIMEOUT=5 \
    POLL_INTERVAL=0.2 \
    "${BATS_CWD}/scripts/check_apiready.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ event=apiready ]]
  [[ "$output" =~ outcome=ok ]]
  [[ ! "$output" =~ mode=alive ]]
  [ -f "${ATTEMPT_FILE}" ]
  [ "$(cat "${ATTEMPT_FILE}")" -ge 2 ]
}
