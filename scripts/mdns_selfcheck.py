#!/usr/bin/env python3
"""Perform targeted mDNS discovery with TXT-aware filtering."""
from __future__ import annotations

import argparse
import ipaddress
import subprocess
import sys
import time
from typing import Callable, Dict, Iterable, List, Optional

from k3s_mdns_parser import parse_avahi_browse_record
from mdns_helpers import norm_host

Record = Dict[str, object]

Logger = Callable[[str], None]
Resolver = Callable[..., List[Record]]
SleepFn = Callable[[float], None]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _stderr_logger(message: str) -> None:
    print(f"{_timestamp()} {message}", file=sys.stderr)


def _is_ipv4(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).version == 4
    except ValueError:
        return False


def _primary_address(addresses: Iterable[str]) -> str:
    ipv4 = next((addr for addr in addresses if _is_ipv4(addr)), None)
    if ipv4:
        return ipv4
    for candidate in addresses:
        if candidate:
            return candidate
    return ""


def _normalise_addresses(record: Record) -> Record:
    addresses = [addr for addr in record.get("addresses", []) if addr]
    record["addresses"] = addresses
    record["addr"] = _primary_address(addresses)
    return record


def resolve_with_resolvectl(
    instance: str,
    service_type: str,
    domain: str = "local",
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> List[Record]:
    command = [
        "resolvectl",
        "service",
        instance,
        service_type,
        domain,
        "--legend=no",
    ]
    try:
        proc = runner(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []

    stdout = proc.stdout or ""
    records: List[Record] = []
    current: Optional[Record] = None

    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if current is not None:
                records.append(_normalise_addresses(current))
                current = None
            continue
        if not line.startswith(" "):
            if current is not None:
                records.append(_normalise_addresses(current))
            parts = line.split()
            if len(parts) < 3:
                current = None
                continue
            current = {
                "instance": parts[0],
                "type": parts[1],
                "domain": parts[2],
                "host": "",
                "addresses": [],
                "port": None,
                "txt": {},
                "source": "resolvectl",
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key == "port":
            try:
                current["port"] = int(value)
            except ValueError:
                current["port"] = None
        elif key in {"target", "host"}:
            current["host"] = value
        elif key in {"address", "a", "aaaa"}:
            if value:
                current.setdefault("addresses", []).append(value)
        elif key == "txt":
            if value:
                txt_key, sep, txt_value = value.partition("=")
                txt_key = txt_key.strip().lower()
                if txt_key:
                    current.setdefault("txt", {})[txt_key] = txt_value.strip() if sep else ""
    if current is not None:
        records.append(_normalise_addresses(current))

    for record in records:
        if not record.get("port"):
            record["port"] = 0
    return records


def resolve_with_avahi_browse(
    service_type: str,
    domain: str = "local",
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> List[Record]:
    command = ["avahi-browse", "-rptk", service_type, "-d", domain]
    try:
        proc = runner(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []

    records: List[Record] = []
    for raw_line in proc.stdout.splitlines():
        if not raw_line:
            continue
        parsed = parse_avahi_browse_record(raw_line)
        if not parsed:
            continue
        addresses: List[str] = []
        address_field = str(parsed.get("address", ""))
        if address_field:
            addresses.append(address_field)
        txt = dict(parsed.get("txt", {}))
        for key in ("a", "addr"):
            value = txt.get(key)
            if value:
                addresses.append(value)
        record: Record = {
            "instance": str(parsed.get("instance", "")),
            "type": str(parsed.get("type", "")),
            "domain": str(parsed.get("domain", "")) or domain,
            "host": str(parsed.get("host", "")),
            "addresses": addresses,
            "port": parsed.get("port") or 0,
            "txt": txt,
            "source": "avahi-browse",
        }
        records.append(_normalise_addresses(record))
    return records


def _instance_key(value: str) -> tuple[str, str, str]:
    value = value.strip()
    if "@" not in value:
        return (value.lower(), "", "")
    prefix, suffix = value.split("@", 1)
    role = ""
    host_part = suffix
    if " (" in suffix and suffix.endswith(")"):
        host_part, role_part = suffix.rsplit(" (", 1)
        role = role_part[:-1].strip().lower()
    host_norm = norm_host(host_part)
    return (prefix.strip().lower(), host_norm, role)


def _format_addresses(addresses: Iterable[str]) -> str:
    return ", ".join(addr for addr in addresses if addr) or "<none>"


def _record_matches(
    record: Record,
    *,
    expected_host: Optional[str],
    expected_ip: Optional[str],
    require_phase: Optional[str],
    require_role: Optional[str],
    require_ipv4: bool,
    logger: Logger,
) -> bool:
    txt = record.get("txt", {}) or {}
    reasons: List[str] = []

    if expected_host:
        observed_host = str(record.get("host", ""))
        host_norm = norm_host(observed_host)
        expected_norm = norm_host(expected_host)
        if host_norm != expected_norm:
            reasons.append(
                "host mismatch"
                f" raw={observed_host or '<missing>'} norm={host_norm or '<empty>'}"
                f" expected_raw={expected_host} expected_norm={expected_norm or '<empty>'}"
            )

    if require_phase:
        phase = txt.get("phase")
        role = txt.get("role")
        if not phase:
            reasons.append(
                f"require_phase={require_phase} but phase=<missing> role={role or '<missing>'}"
            )
        elif phase != require_phase:
            reasons.append(
                f"require_phase={require_phase} but phase={phase}"
            )

    if require_role:
        role_value = txt.get("role")
        if not role_value:
            reasons.append(
                f"require_role={require_role} but role=<missing>"
            )
        elif role_value != require_role:
            reasons.append(
                f"require_role={require_role} but role={role_value}"
            )

    addresses = record.get("addresses", [])
    if expected_ip:
        if expected_ip not in addresses:
            reasons.append(
                "expected_ip="
                f"{expected_ip} not observed (addresses={_format_addresses(addresses)})"
            )
    if require_ipv4 and not any(_is_ipv4(addr) for addr in addresses):
        reasons.append(
            f"require_ipv4 but observed addresses={_format_addresses(addresses)}"
        )

    if reasons:
        logger(
            "[mdns-selfcheck] skipping"
            f" instance={record.get('instance', '<unknown>')}"
            f" source={record.get('source', '<unknown>')}"
            f"; {'; '.join(reasons)}"
        )
        return False
    return True


def _filter_records_by_instance(records: List[Record], instance: str) -> List[Record]:
    if not instance:
        return records
    target = _instance_key(instance)
    filtered: List[Record] = []
    for record in records:
        candidate = _instance_key(str(record.get("instance", "")))
        if candidate == target:
            filtered.append(record)
    return filtered


def run_selfcheck(
    *,
    instance: str,
    service_type: str,
    domain: str,
    expected_host: Optional[str],
    expected_ip: Optional[str],
    require_phase: Optional[str],
    require_role: Optional[str],
    require_ipv4: bool,
    retries: int,
    delay: float,
    logger: Logger = _stderr_logger,
    resolvectl: Resolver = resolve_with_resolvectl,
    avahi: Resolver = resolve_with_avahi_browse,
    sleep: SleepFn = time.sleep,
) -> Optional[Record]:
    attempts = max(retries, 1)
    delay = max(delay, 0.0)

    for attempt in range(1, attempts + 1):
        records = resolvectl(instance, service_type, domain=domain)
        if records:
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                f" resolvectl returned {len(records)} record(s)"
            )
        else:
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                " resolvectl returned no records"
            )

        for record in records:
            if _record_matches(
                record,
                expected_host=expected_host,
                expected_ip=expected_ip,
                require_phase=require_phase,
                require_role=require_role,
                require_ipv4=require_ipv4,
                logger=logger,
            ):
                return record

        if records:
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                " resolvectl did not yield a matching record; trying avahi-browse"
            )
        else:
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                " falling back to avahi-browse due to empty resolvectl response"
            )

        raw_records = avahi(service_type, domain=domain)
        if raw_records:
            filtered_records = _filter_records_by_instance(raw_records, instance)
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                f" avahi-browse returned {len(raw_records)} record(s);"
                f" {len(filtered_records)} matched instance"
            )
        else:
            filtered_records = []
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                " avahi-browse returned no records"
            )

        for record in filtered_records:
            if _record_matches(
                record,
                expected_host=expected_host,
                expected_ip=expected_ip,
                require_phase=require_phase,
                require_role=require_role,
                require_ipv4=require_ipv4,
                logger=logger,
            ):
                return record

        if attempt < attempts and delay:
            logger(
                f"[mdns-selfcheck] attempt {attempt}/{attempts}:"
                f" sleeping for {delay:.3f}s before retry"
            )
            sleep(delay)

    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--type", dest="service_type", required=True)
    parser.add_argument("--domain", default="local")
    parser.add_argument("--expected-host", dest="expected_host")
    parser.add_argument("--expected-ip", dest="expected_ip")
    parser.add_argument("--require-phase", dest="require_phase")
    parser.add_argument("--require-role", dest="require_role")
    parser.add_argument("--require-ipv4", action="store_true")
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--delay-ms", type=float, default=500.0)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    delay_seconds = max(args.delay_ms, 0.0) / 1000.0

    record = run_selfcheck(
        instance=args.instance,
        service_type=args.service_type,
        domain=args.domain,
        expected_host=args.expected_host,
        expected_ip=args.expected_ip,
        require_phase=args.require_phase,
        require_role=args.require_role,
        require_ipv4=args.require_ipv4,
        retries=args.retries,
        delay=delay_seconds,
    )
    if record:
        host = str(record.get("host", ""))
        print(host)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
