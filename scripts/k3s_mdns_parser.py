"""Helpers for parsing resolved Avahi browse output for k3s services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class MdnsRecord:
    """Structured representation of an mDNS record for the k3s API."""

    host: str
    address: str
    port: int
    protocol: str
    txt: Dict[str, str]
    raw: str


def _is_candidate_line(line: str) -> bool:
    return bool(line) and line[0] in {"=", "+", "@"}


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


def parse_mdns_records(
    lines: Iterable[str], cluster: str, environment: str
) -> List[MdnsRecord]:
    """Parse Avahi browse output into structured records.

    Parameters
    ----------
    lines:
        Iterable of resolved browse lines. Each line should already include TXT
        payloads via ``--resolve``.
    cluster:
        Expected cluster identifier.
    environment:
        Expected environment identifier.

    Returns
    -------
    list of MdnsRecord
        Records filtered to the requested cluster/env, with IPv4 preferred when
        both address families are advertised for the same host/role pair.
    """

    candidates: Dict[Tuple[str, str], MdnsRecord] = {}

    for raw in lines:
        if not _is_candidate_line(raw):
            continue
        fields = raw.split(";")
        if len(fields) < 9:
            continue

        service_type = fields[4]
        if service_type != "_https._tcp":
            continue

        port_field = fields[8]
        if port_field != "6443":
            continue

        txt = _parse_txt_fields(fields[9:])
        if txt.get("k3s") != "1":
            continue
        if txt.get("cluster") != cluster:
            continue
        if txt.get("env") != environment:
            continue

        host = fields[6]
        address = fields[7] if len(fields) > 7 else ""
        protocol = fields[2] if len(fields) > 2 else ""
        role = txt.get("role", "")
        key = (host, role)

        record = MdnsRecord(
            host=host,
            address=address,
            port=int(port_field),
            protocol=protocol,
            txt=txt,
            raw=raw,
        )

        existing = candidates.get(key)
        if existing is None:
            candidates[key] = record
            continue

        if existing.protocol == "IPv6" and protocol == "IPv4":
            candidates[key] = record

    return list(candidates.values())


__all__ = ["MdnsRecord", "parse_mdns_records"]
