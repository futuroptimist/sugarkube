#!/usr/bin/env python3
"""List published k3s mDNS records for debugging."""

import json
import os
import subprocess

from k3s_mdns_parser import parse_mdns_records


def main() -> int:
    cluster = os.environ.get("SUGARKUBE_CLUSTER", "sugar")
    environment = os.environ.get("SUGARKUBE_ENV", "dev")
    service_type = f"_k3s-{cluster}-{environment}._tcp"

    proc = subprocess.run(
        ["avahi-browse", "-rptk", service_type],
        check=False,
        capture_output=True,
        text=True,
    )

    lines = [line for line in proc.stdout.splitlines() if line]
    records = parse_mdns_records(lines, cluster, environment)

    payload = []
    for record in records:
        entry = {
            "host": record.host,
            "ipv4": record.address if record.address and ":" not in record.address else "",
            "port": record.port,
        }
        for key in ("phase", "role", "leader", "host"):
            if key in record.txt:
                entry[key] = record.txt[key]
        payload.append(entry)

    print(json.dumps(payload, indent=2))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
