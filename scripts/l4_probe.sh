#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE' >&2
Usage: l4_probe.sh HOST PORTS

HOST   Hostname or IP address to probe.
PORTS  Comma-separated list of TCP ports to test.
USAGE
}

if [ "$#" -ne 2 ]; then
  usage
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to run l4_probe.sh" >&2
  exit 2
fi

HOST="$1"
PORT_SPEC="$2"

IFS=',' read -r -a PORT_LIST <<<"${PORT_SPEC}"

if [ "${#PORT_LIST[@]}" -eq 0 ]; then
  echo "No ports provided" >&2
  exit 2
fi

TIMEOUT="${L4_PROBE_TIMEOUT:-3}"

CLEAN_PORTS=()
for raw_port in "${PORT_LIST[@]}"; do
  port="${raw_port//[[:space:]]/}"
  if [ -z "${port}" ]; then
    continue
  fi
  if ! [[ "${port}" =~ ^[0-9]+$ ]]; then
    echo "Invalid port: ${raw_port}" >&2
    exit 2
  fi
  CLEAN_PORTS+=("${port}")
done

if [ "${#CLEAN_PORTS[@]}" -eq 0 ]; then
  echo "No valid ports provided" >&2
  exit 2
fi

export PYTHONUNBUFFERED=1

python3 - "$HOST" "$TIMEOUT" "${CLEAN_PORTS[@]}" <<'PYTHON'
import json
import socket
import sys
import time

host = sys.argv[1]
try:
    timeout = float(sys.argv[2])
except ValueError:
    print("Invalid timeout value", file=sys.stderr)
    sys.exit(2)

ports = []
for value in sys.argv[3:]:
    try:
        ports.append(int(value))
    except ValueError:
        print(f"Invalid port: {value}", file=sys.stderr)
        sys.exit(2)

results = []
exit_code = 0

for port in ports:
    start = time.perf_counter()
    status = "open"
    error = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except Exception as exc:  # noqa: BLE001
        status = "closed"
        error = str(exc)
        exit_code = 1
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass
    latency_ms = int((time.perf_counter() - start) * 1000)
    result = {
        "host": host,
        "port": port,
        "status": status,
        "latency_ms": latency_ms,
    }
    if error:
        result["error"] = error
    results.append(result)

for entry in results:
    print(json.dumps(entry, separators=(",", ":")))

sys.exit(exit_code)
PYTHON
