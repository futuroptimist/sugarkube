#!/usr/bin/env python3
"""Sanitize and tee `just up` output to a log file."""

from __future__ import annotations

import argparse
import datetime as _dt
import ipaddress
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Pattern


PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

SENSITIVE_ENV_TOKENS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "BEARER")
REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_IP = "[REDACTED_IP]"


def _build_secret_patterns(env: Iterable[tuple[str, str]]) -> list[tuple[Pattern[str], str]]:
    patterns: list[tuple[Pattern[str], str]] = []
    for name, value in env:
        if not value:
            continue
        upper_name = name.upper()
        if not any(marker in upper_name for marker in SENSITIVE_ENV_TOKENS):
            continue
        if len(value) < 5:
            continue
        escaped = re.escape(value)
        try:
            pattern = re.compile(escaped)
        except re.error:
            continue
        patterns.append((pattern, REDACTED_SECRET))
    return patterns


def _is_external_ip(candidate: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    for network in PRIVATE_NETWORKS:
        if ip_obj in network:
            return False
    return True


def _sanitize_ips(line: str) -> str:
    def replace_ipv4(match: re.Match[str]) -> str:
        token = match.group(1)
        if _is_external_ip(token):
            return REDACTED_IP
        return token

    def replace_ipv6(match: re.Match[str]) -> str:
        token = match.group(1)
        if not any(char.isalnum() for char in token):
            return token
        if _is_external_ip(token):
            return REDACTED_IP
        return token

    ipv4_pattern = re.compile(
        r"(?<![:\d])("  # avoid matching timestamps or IPv6 segments
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
        r"(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}"
        r")"
    )
    line = ipv4_pattern.sub(replace_ipv4, line)

    ipv6_candidates = re.compile(
        r"(?<![0-9A-Fa-f:.])"  # ensure we start at a boundary
        r"([0-9A-Fa-f:.]*:[0-9A-Fa-f:.]+)"  # require at least one colon
        r"(?![0-9A-Fa-f:.])"
    )
    return ipv6_candidates.sub(replace_ipv6, line)


def sanitize_line(line: str, secret_patterns: list[tuple[Pattern[str], str]]) -> str:
    sanitized = line
    for pattern, replacement in secret_patterns:
        sanitized = pattern.sub(replacement, sanitized)
    sanitized = _sanitize_ips(sanitized)
    sanitized = re.sub(r"Authorization:\s*\S+", "Authorization: " + REDACTED_SECRET, sanitized, flags=re.IGNORECASE)
    return sanitized


def main() -> int:
    parser = argparse.ArgumentParser(description="Sanitize output and tee to a log file")
    parser.add_argument("--log", required=True, help="Path to the log file that should capture sanitized output")
    parser.add_argument(
        "--source",
        default="just up",
        help="Friendly source label written to the log header for traceability",
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    secret_patterns = _build_secret_patterns(os.environ.items())

    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    header = [
        "# Sugarkube debug log (sanitized)",
        f"# Source: {args.source}",
        f"# Generated: {now}",
        "# Secrets and external IP addresses have been redacted.",
        "",
    ]

    with log_path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(header))
        handle.flush()
        for raw_line in sys.stdin:
            stripped = raw_line.rstrip("\n")
            sanitized = sanitize_line(stripped, secret_patterns)
            handle.write(sanitized + "\n")
            handle.flush()
            sys.stdout.write(raw_line)
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
