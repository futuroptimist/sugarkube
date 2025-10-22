#!/usr/bin/env python3
"""Utility helpers for parsing k3s mDNS advertisements."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass
class MdnsRecord:
    """Resolved mDNS entry for the Kubernetes API."""

    raw: str
    host: str
    address: str
    port: str
    protocol: str
    role: str
    txt: Dict[str, str]


def _run_avahi_browse() -> List[str]:
    """Execute avahi-browse with the required flags and capture its output."""

    # --resolve ensures we receive the host, IP, and TXT payloads.
    # --ignore-local avoids matching our own bootstrap adverts.
    command = [
        "avahi-browse",
        "--parsable",
        "--terminate",
        "--resolve",
        "--ignore-local",
        "_https._tcp",
    ]
    try:
        output = subprocess.check_output(
            command,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _parse_txt(fields: Sequence[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for field in fields:
        if not field.startswith("txt="):
            continue
        payload = field[4:]
        if "=" in payload:
            key, value = payload.split("=", 1)
        else:
            key, value = payload, ""
        result[key] = value
    return result


def parse_records(
    lines: Iterable[str],
    cluster: str,
    environment: str,
) -> List[MdnsRecord]:
    """Filter avahi-browse output for the target cluster/environment."""

    records: List[MdnsRecord] = []
    best_index: Dict[Tuple[str, str], int] = {}

    for line in lines:
        if not line or line[0] not in {"=", "+", "@"}:
            continue
        fields = line.split(";")
        if len(fields) < 9:
            continue
        service_type = fields[4]
        if service_type != "_https._tcp":
            continue
        port = fields[8]
        if port != "6443":
            continue
        host = fields[6]
        address = fields[7]
        protocol = fields[2]
        txt = _parse_txt(fields[9:])
        if txt.get("k3s") != "1":
            continue
        if txt.get("cluster") != cluster:
            continue
        if txt.get("env") != environment:
            continue
        role = txt.get("role", "")
        if not host:
            continue
        record = MdnsRecord(
            raw=line,
            host=host,
            address=address,
            port=port,
            protocol=protocol,
            role=role,
            txt=txt,
        )
        key = (role, host)
        existing_index = best_index.get(key)
        if existing_index is None:
            best_index[key] = len(records)
            records.append(record)
            continue
        existing = records[existing_index]
        if existing.protocol != "IPv4" and record.protocol == "IPv4":
            records[existing_index] = record
    return records


def _dump_debug(lines: Sequence[str]) -> None:
    try:
        Path("/tmp/sugarkube-mdns.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"[k3s-discover mdns] failed to write debug dump: {exc}", file=sys.stderr)


def _emit(mode: str, records: List[MdnsRecord]) -> int:
    if mode == "server-first":
        for record in records:
            if record.role == "server":
                print(record.host)
                break
        return 0
    if mode == "server-count":
        count = sum(1 for record in records if record.role == "server")
        print(count)
        return 0
    if mode == "bootstrap-hosts":
        seen_hosts: set[str] = set()
        for record in records:
            if record.role != "bootstrap":
                continue
            if record.host in seen_hosts:
                continue
            seen_hosts.add(record.host)
            print(record.host)
        return 0
    if mode == "bootstrap-leaders":
        seen_leaders: set[str] = set()
        for record in records:
            if record.role != "bootstrap":
                continue
            leader = record.txt.get("leader", record.host)
            if leader in seen_leaders:
                continue
            seen_leaders.add(leader)
            print(leader)
        return 0
    print(f"Unknown mode: {mode}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) != 3:
        print("usage: mdns_parser.py MODE CLUSTER ENV", file=sys.stderr)
        return 2
    mode, cluster, environment = args

    raw_lines = _run_avahi_browse()
    records = parse_records(raw_lines, cluster, environment)

    debug_enabled = bool(os.environ.get("SUGARKUBE_DEBUG"))
    has_servers = any(record.role == "server" for record in records)
    if debug_enabled and not has_servers and raw_lines:
        _dump_debug(raw_lines)

    return _emit(mode, records)


if __name__ == "__main__":
    sys.exit(main())
