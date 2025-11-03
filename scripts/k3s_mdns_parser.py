"""Helpers for parsing resolved Avahi browse output for k3s services."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from mdns_helpers import _norm_host

_SERVICE_NAME_RE = re.compile(
    r"^k3s API (?P<cluster>[^/]+)/(?P<environment>\S+)"
    r"(?: \[(?P<role>[^\]]+)\])? on (?P<host>.+)$"
)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _normalize_role(role: Optional[str]) -> Optional[str]:
    if role is None:
        return None
    return role.strip().lower() or None


def _normalize_host(host: str, domain: str) -> str:
    host = host.strip().rstrip(".")
    domain = domain.strip().rstrip(".")
    if not host:
        return ""

    domain_lower = domain.lower()
    host_compare = host.lower()

    if domain_lower and not host_compare.endswith(f".{domain_lower}"):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            host = f"{host}.{domain_lower}" if domain_lower else host

    if domain_lower and "." in host:
        parts = host.split(".")
        if parts[-1].lower() == domain_lower:
            parts[-1] = domain_lower
            host = ".".join(parts)

    return host


def _parse_service_name(
    service_name: str, domain: str
) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    match = _SERVICE_NAME_RE.match(service_name)
    if match:
        cluster = match.group("cluster")
        environment = match.group("environment")
        role = _normalize_role(match.group("role"))
        host = _normalize_host(match.group("host"), domain)
        return cluster, environment, role, host

    if service_name.startswith("k3s-") and "@" in service_name:
        slug, host_part = service_name.split("@", 1)
        slug_body = slug[4:] if slug.startswith("k3s-") else slug
        cluster = None
        environment = None
        if slug_body and "-" in slug_body:
            cluster, environment = slug_body.rsplit("-", 1)
        host_part = host_part.strip()
        role = None
        if " (" in host_part and host_part.endswith(")"):
            host_candidate, suffix = host_part.rsplit(" (", 1)
            suffix = suffix.rstrip(")")
            candidate_role = _normalize_role(suffix)
            if candidate_role:
                role = candidate_role
                host_part = host_candidate
        host = _normalize_host(host_part, domain)
        return cluster, environment, role, host

    return None, None, None, ""


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
        field = field.strip()
        if not field:
            continue
        field = _strip_quotes(field)
        if not field.startswith("txt="):
            continue
        payload = field[4:]
        if not payload:
            continue
        payload = _strip_quotes(payload.strip())
        if not payload:
            continue
        entries = [payload]
        if "," in payload and "=" in payload:
            entries = [item.strip() for item in payload.split(",") if item.strip()]
        for entry in entries:
            entry = _strip_quotes(entry.strip())
            if not entry:
                continue
            if "=" in entry:
                key, value = entry.split("=", 1)
                key = key.strip().lower()
                value = _strip_quotes(value.strip())
            else:
                key = entry.strip().lower()
                value = ""
            if key:
                txt[key] = value
    return txt


def parse_avahi_resolved_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single ``avahi-browse -p -r`` resolved line."""

    if not _is_candidate_line(line):
        return None

    parts = line.split(";")
    if len(parts) < 6:
        return None
    if len(parts) < 9:
        parts = parts + [""] * (9 - len(parts))

    cleaned = [_strip_quotes(part.strip()) for part in parts]

    txt = _parse_txt_fields(cleaned[9:]) if len(cleaned) > 9 else {}

    host = cleaned[6] if len(cleaned) > 6 else ""
    addr = cleaned[7] if len(cleaned) > 7 else ""
    port_raw = cleaned[8] if len(cleaned) > 8 else ""
    try:
        port = int(port_raw) if port_raw else 0
    except ValueError:
        port = 0

    return {
        "raw": line,
        "record_type": cleaned[0],
        "interface": cleaned[1] if len(cleaned) > 1 else "",
        "protocol": cleaned[2] if len(cleaned) > 2 else "",
        "instance": cleaned[3] if len(cleaned) > 3 else "",
        "type": cleaned[4] if len(cleaned) > 4 else "",
        "domain": cleaned[5] if len(cleaned) > 5 else "",
        "host": host,
        "addr": addr,
        "port": port,
        "port_raw": port_raw,
        "txt": txt,
        "fields": cleaned,
    }


def _txt_is_richer(existing: Dict[str, str], new: Dict[str, str]) -> bool:
    """Return True when ``new`` contains more information than ``existing``."""

    if len(new) > len(existing):
        return True

    for key, value in new.items():
        if value and not existing.get(key):
            return True

    return False


def parse_mdns_records(lines: Iterable[str], cluster: str, environment: str) -> List[MdnsRecord]:
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
    expected_cluster = cluster.strip().lower()
    expected_env = environment.strip().lower()

    for raw in lines:
        parsed = parse_avahi_resolved_line(raw)
        if not parsed:
            continue

        service_type = parsed["type"]
        type_cluster: Optional[str] = None
        type_environment: Optional[str] = None

        if service_type == "_https._tcp":
            pass
        elif service_type.startswith("_k3s-") and service_type.endswith("._tcp"):
            slug = service_type[len("_k3s-") : -len("._tcp")]
            if "-" in slug:
                type_cluster, type_environment = slug.rsplit("-", 1)
        else:
            continue

        domain = parsed["domain"]
        service_cluster, service_env, service_role, service_host = _parse_service_name(
            parsed["instance"],
            domain,
        )

        if type_cluster and not service_cluster:
            service_cluster = type_cluster
        if type_environment and not service_env:
            service_env = type_environment

        if service_cluster:
            service_cluster = service_cluster.strip()
        if service_env:
            service_env = service_env.strip()
        if type_cluster:
            type_cluster = type_cluster.strip()
        if type_environment:
            type_environment = type_environment.strip()

        txt = parsed["txt"].copy()
        if "leader" in txt:
            txt["leader"] = _normalize_host(txt["leader"], domain)
        if "phase" in txt and txt["phase"]:
            txt["phase"] = txt["phase"].lower()
        if "role" in txt and txt["role"]:
            txt["role"] = _normalize_role(txt["role"])
        if txt.get("k3s") != "1" and not service_cluster:
            continue

        cluster_value = txt.get("cluster") or service_cluster or type_cluster
        environment_value = txt.get("env") or service_env or type_environment
        cluster_value_norm = cluster_value.strip().lower() if cluster_value else ""
        environment_value_norm = environment_value.strip().lower() if environment_value else ""
        if cluster_value_norm != expected_cluster or environment_value_norm != expected_env:
            continue

        if cluster:
            txt["cluster"] = cluster
        if environment:
            txt["env"] = environment

        host = ""
        if parsed["host"]:
            host = _normalize_host(parsed["host"], domain)
        elif service_host:
            host = service_host
        if not host:
            host = txt.get("leader", "")
            if host:
                host = _normalize_host(host, domain)
        if not host:
            continue

        protocol = parsed["protocol"]
        address = parsed["addr"]

        port = parsed["port"] or 6443

        role = _normalize_role(txt.get("role")) or service_role
        if role is None and not txt:
            role = "bootstrap"

        if role:
            txt["role"] = role
        if "k3s" not in txt:
            txt["k3s"] = "1"
        if txt.get("role") == "bootstrap" and "leader" not in txt:
            txt["leader"] = host

        key = (_norm_host(host), txt.get("role", ""))

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


__all__ = ["MdnsRecord", "parse_avahi_resolved_line", "parse_mdns_records"]
