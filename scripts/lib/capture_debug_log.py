#!/usr/bin/env python3
"""Capture `just up` logs safely when SAVE_DEBUG_LOGS is enabled."""
from __future__ import annotations

import ipaddress
import os
import re
import sys
from pathlib import Path
from typing import Iterable

MASK_SECRET = "<REDACTED>"
MASK_IP = "<REDACTED_IP>"

SAFE_IPV4_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
]

SAFE_IPV6_NETWORKS = [
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
]


def _load_mask_values() -> list[str]:
    path = os.environ.get("SUGARKUBE_DEBUG_MASK_FILE")
    if not path:
        return []
    mask_path = Path(path)
    if not mask_path.exists():
        return []
    values: list[str] = []
    try:
        for line in mask_path.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if candidate:
                values.append(candidate)
    except OSError:
        return []
    return values


def _mask_secrets(line: str, secrets: Iterable[str]) -> str:
    result = line
    for secret in secrets:
        if secret:
            result = result.replace(secret, MASK_SECRET)
    return result


IP_CANDIDATE_PATTERN = re.compile(r"(?<![0-9A-Fa-f:.])[0-9A-Fa-f:.]{2,}(?![0-9A-Fa-f:.])")


def _mask_ip_addresses(line: str) -> str:
    result: list[str] = []
    last = 0
    for match in IP_CANDIDATE_PATTERN.finditer(line):
        ip = match.group(0)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        result.append(line[last:match.start()])
        if _should_mask_ip(addr):
            result.append(MASK_IP)
        else:
            result.append(ip)
        last = match.end()
    result.append(line[last:])
    return "".join(result)


def _should_mask_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(addr, ipaddress.IPv4Address):
        networks = SAFE_IPV4_NETWORKS
    else:
        networks = SAFE_IPV6_NETWORKS
    for network in networks:
        if addr in network:
            return False
    return True


def sanitize_line(line: str, secrets: Iterable[str]) -> str:
    sanitized = _mask_secrets(line, secrets)
    sanitized = _mask_ip_addresses(sanitized)
    return sanitized


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: capture_debug_log.py <log_path>", file=sys.stderr)
        return 1
    log_path = Path(sys.argv[1]).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    secrets = _load_mask_values()

    try:
        with log_path.open("a", encoding="utf-8") as handle:
            for raw_line in sys.stdin:
                sanitized = sanitize_line(raw_line.rstrip("\n"), secrets)
                print(sanitized)
                handle.write(sanitized + "\n")
                handle.flush()
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
