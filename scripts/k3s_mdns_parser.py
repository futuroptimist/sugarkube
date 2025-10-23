"""Helpers for parsing resolved Avahi browse output for k3s services."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_SERVICE_NAME_RE = re.compile(
    r"^k3s API (?P<cluster>[^/]+)/(?P<environment>\S+)"
    r"(?: \[(?P<role>[^\]]+)\])? on (?P<host>.+)$"
)


def _normalize_role(role: Optional[str]) -> Optional[str]:
    if role is None:
        return None
    return role.strip().lower() or None


def _normalize_host(host: str, domain: str) -> str:
    host = host.strip()
    if not host:
        return ""
    if domain and not host.endswith(f".{domain}"):
        return f"{host}.{domain}"
    return host


def _parse_service_name(service_name: str, domain: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    match = _SERVICE_NAME_RE.match(service_name)
    if not match:
        return None, None, None, ""
    cluster = match.group("cluster")
    environment = match.group("environment")
    role = _normalize_role(match.group("role"))
    host = _normalize_host(match.group("host"), domain)
    return cluster, environment, role, host


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


def _txt_is_richer(existing: Dict[str, str], new: Dict[str, str]) -> bool:
    """Return True when ``new`` contains more information than ``existing``."""

    if len(new) > len(existing):
        return True

    for key, value in new.items():
        if value and not existing.get(key):
            return True

    return False


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
        if len(fields) < 6:
            continue

        service_type = fields[4]
        if service_type != "_https._tcp":
            continue

        domain = fields[5] if len(fields) > 5 else ""
        service_cluster, service_env, service_role, service_host = _parse_service_name(
            fields[3] if len(fields) > 3 else "",
            domain,
        )

        txt = _parse_txt_fields(fields[9:]) if len(fields) > 9 else {}
        if txt.get("k3s") != "1" and not service_cluster:
            continue

        cluster_value = txt.get("cluster") or service_cluster
        environment_value = txt.get("env") or service_env
        if cluster_value != cluster or environment_value != environment:
            continue

        host = ""
        if len(fields) > 6 and fields[6]:
            host = fields[6]
        elif service_host:
            host = service_host
        if not host:
            continue

        protocol = fields[2] if len(fields) > 2 else ""
        address = fields[7] if len(fields) > 7 else ""

        port_field = fields[8] if len(fields) > 8 else ""
        if port_field:
            try:
                port = int(port_field)
            except ValueError:
                continue
        else:
            port = 6443

        role = _normalize_role(txt.get("role")) or service_role
        if role is None and not txt:
            role = "bootstrap"

        if role:
            txt["role"] = role
        if "k3s" not in txt:
            txt["k3s"] = "1"
        if "cluster" not in txt and service_cluster:
            txt["cluster"] = service_cluster
        if "env" not in txt and service_env:
            txt["env"] = service_env
        if txt.get("role") == "bootstrap" and "leader" not in txt:
            txt["leader"] = host

        key = (host, txt.get("role", ""))

        record = MdnsRecord(
            host=host,
            address=address,
            port=port,
            protocol=protocol,
            txt=txt,
            raw=raw,
        )

        existing = candidates.get(key)
        if existing is None:
            candidates[key] = record
            continue

        replace = False

        if existing.protocol == "IPv6" and protocol == "IPv4":
            replace = True
        elif address and not existing.address:
            replace = True
        elif _txt_is_richer(existing.txt, txt):
            replace = True

        if replace:
            candidates[key] = record

    return list(candidates.values())


__all__ = ["MdnsRecord", "parse_mdns_records"]
