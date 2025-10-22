"""Utilities for parsing Avahi browse output for k3s discovery."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class MdnsRecord:
    """Resolved mDNS service entry."""

    hostname: str
    address: str
    port: int
    txt: Dict[str, str]
    protocol: str
    raw_line: str


def _parse_txt_fields(fields: Sequence[str]) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    for field in fields:
        if not field.startswith("txt="):
            continue
        payload = field[4:]
        if "=" not in payload:
            continue
        key, value = payload.split("=", 1)
        txt[key] = value
    return txt


def parse_avahi_output(
    output: str, cluster: str, environment: str
) -> Tuple[List[MdnsRecord], List[str]]:
    """Parse avahi-browse output into normalized records.

    Parameters
    ----------
    output:
        Raw output from ``avahi-browse --parsable --resolve``.
    cluster / environment:
        Expected cluster/environment tags stored within TXT records. Only
        matching entries are returned.

    Returns
    -------
    Tuple[List[MdnsRecord], List[str]]
        ``MdnsRecord`` entries keyed by hostname/role with IPv4 preferred when
        both address families are present, plus the raw resolved lines that were
        inspected. The raw lines assist with debugging field offsets when no
        candidates match.
    """

    records: Dict[Tuple[str, str], MdnsRecord] = {}
    resolved_lines: List[str] = []

    for line in output.splitlines():
        if not line or line[0] not in {"=", "+", "@"}:
            continue
        resolved_lines.append(line)
        parts = line.split(";")
        if len(parts) < 9:
            continue

        protocol = parts[2]
        service_type = parts[4]
        if service_type != "_https._tcp":
            continue

        hostname = parts[6]
        address = parts[7]
        port_str = parts[8]
        try:
            port = int(port_str)
        except ValueError:
            continue
        if port != 6443:
            continue

        txt = _parse_txt_fields(parts[9:])
        if txt.get("k3s") != "1":
            continue
        if txt.get("cluster") != cluster:
            continue
        if txt.get("env") != environment:
            continue

        role = txt.get("role", "")
        key = (hostname, role)
        record = MdnsRecord(
            hostname=hostname,
            address=address,
            port=port,
            txt=txt,
            protocol=protocol,
            raw_line=line,
        )

        existing = records.get(key)
        if existing is None or (existing.protocol != "IPv4" and protocol == "IPv4"):
            records[key] = record

    return list(records.values()), resolved_lines


__all__ = ["MdnsRecord", "parse_avahi_output"]
