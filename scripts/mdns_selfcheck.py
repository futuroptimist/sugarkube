#!/usr/bin/env python3
"""Filter avahi-browse output into structured JSON records."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List


def parse_records(service: str, lines: List[str]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line[0] not in "=+@":
            continue
        parts = line.split(";")
        if len(parts) < 9:
            continue
        host = parts[6]
        ipv4 = parts[7]
        port_field = parts[8]
        txt_values: Dict[str, str] = {}
        for token in parts[9:]:
            if not token.startswith("txt="):
                continue
            payload = token[4:].strip()
            if not payload:
                continue
            entries = [payload]
            if "," in payload:
                entries = [item.strip() for item in payload.split(",") if item.strip()]
            for entry in entries:
                if "=" not in entry:
                    continue
                key, value = entry.split("=", 1)
                key = key.strip().lower()
                value = value.strip()
                if not key:
                    continue
                txt_values[key] = value
        try:
            port: Any = int(port_field)
        except ValueError:
            port = port_field
        records.append(
            {
                "service": service,
                "host": host,
                "ipv4": ipv4,
                "port": port,
                "txt": {
                    "phase": txt_values.get("phase"),
                    "role": txt_values.get("role"),
                    "leader": txt_values.get("leader"),
                    "host": txt_values.get("host"),
                },
            }
        )
    return records


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: mdns_selfcheck.py SERVICE", file=sys.stderr)
        return 1

    service = sys.argv[1]
    records = parse_records(service, list(sys.stdin))
    json.dump(records, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
