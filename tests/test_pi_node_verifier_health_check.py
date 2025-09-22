import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT_PATH = Path("scripts/pi_node_verifier.sh")


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format, *args):  # noqa: D401
        return


def test_token_place_health_check_passes():
    server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = os.environ.copy()
        env.update(
            {
                "TOKEN_PLACE_HEALTH_URL": f"http://127.0.0.1:{port}/",
                "DSPACE_HEALTH_URL": "skip",
                "HEALTH_TIMEOUT": "2",
            }
        )
        cmd = ["/bin/bash", str(SCRIPT_PATH), "--no-log"]
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    finally:
        server.shutdown()
        thread.join(timeout=1)

    assert "token_place_http: pass" in result.stdout
