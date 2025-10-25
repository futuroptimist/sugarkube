#!/usr/bin/env python3
"""Verify that k3s mDNS advertisements expose expected TXT metadata."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
import time
from typing import Callable, Dict, Iterable, List, Optional

from mdns_helpers import norm_host
from k3s_mdns_parser import parse_avahi_resolved_line


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _log(message: str) -> None:
    print(f"{_timestamp()} {message}", file=sys.stderr)


def _strip_token(token: str) -> str:
    return token.strip().strip(",[]()")


def _parse_txt_tokens(tokens: Iterable[str]) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    for token in tokens:
        cleaned = _strip_token(token)
        if not cleaned:
            continue
        if "=" in cleaned:
            key, value = cleaned.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
        else:
            key = cleaned.strip().lower()
            value = ""
        if key:
            txt[key] = value
    return txt


def resolve_with_resolvectl(
    instance: str,
    service_type: str,
    domain: str = "local",
    *,
    runner: Runner = subprocess.run,
) -> List[Dict[str, object]]:
    """Resolve a service using ``resolvectl service`` and capture TXT data."""

    cmd = ["resolvectl", "service", instance, service_type, domain, "--legend=no"]
    try:
        proc = runner(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []

    stdout = proc.stdout if proc.stdout else ""
    records: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                records.append(current)
                current = None
            continue

        if current is None:
            full_name, _, remainder = line.partition(":")
            remainder = remainder.strip()
            host = ""
            port = 0
            if remainder:
                head = remainder.split()[0]
                host_part, sep, port_part = head.partition(":")
                host = host_part.strip()
                if sep and port_part.isdigit():
                    port = int(port_part)
            current = {
                "instance": full_name.strip(),
                "type": service_type,
                "domain": domain,
                "host": host,
                "addr": "",
                "port": port,
                "txt": {},
            }
            continue

        upper = line.upper()
        if upper.startswith("TXT:"):
            tokens = line[4:].strip().split()
            current_txt = current.setdefault("txt", {})
            assert isinstance(current_txt, dict)
            current_txt.update(_parse_txt_tokens(tokens))
            continue

        lowered = line.lower()
        if "port" in lowered and isinstance(current.get("port"), int) and current["port"] == 0:
            for token in line.replace(",", " ").split():
                token = token.strip()
                if token.isdigit():
                    current["port"] = int(token)
            continue

        if line.lower().startswith("host ") and not current.get("host"):
            parts = line.split()
            if len(parts) >= 2:
                current["host"] = parts[1]
            continue

        for token in line.replace(":", " ").split():
            candidate = _strip_token(token)
            if not candidate:
                continue
            try:
                ip = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if ip.version == 4 or not current.get("addr"):
                current["addr"] = str(ip)
            if ip.version == 4:
                break

    if current:
        records.append(current)

    # Filter out entries that never populated TXT metadata.
    enriched = [record for record in records if record.get("txt")]
    return enriched if enriched else records


def resolve_with_avahi_browse(
    service_type: str,
    domain: str = "local",
    *,
    runner: Runner = subprocess.run,
) -> List[Dict[str, object]]:
    """Resolve a service snapshot via ``avahi-browse -rptk``."""

    cmd = ["avahi-browse", "-rptk", service_type, "-d", domain]
    try:
        proc = runner(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []

    stdout = proc.stdout if proc.stdout else ""
    records: List[Dict[str, object]] = []
    for line in stdout.splitlines():
        parsed = parse_avahi_resolved_line(line)
        if not parsed:
            continue
        records.append(
            {
                "instance": parsed["instance"],
                "type": parsed["type"],
                "domain": parsed["domain"],
                "host": parsed["host"],
                "addr": parsed["addr"],
                "port": parsed["port"],
                "txt": parsed["txt"],
            }
        )
    return records


def _ipv4_string(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def _record_reason(
    record: Dict[str, object],
    *,
    expected_host: str,
    require_phase: Optional[str],
    require_role: Optional[str],
    expect_addr: Optional[str],
) -> Optional[str]:
    txt = record.get("txt", {}) or {}
    if not isinstance(txt, dict):
        txt = {}
    observed_host = norm_host(str(record.get("host", "")))
    expected_norm = norm_host(expected_host)
    leader_norm = norm_host(txt.get("leader"))

    if expected_norm and observed_host != expected_norm and leader_norm != expected_norm:
        return (
            "host mismatch: raw=%s norm=%s leader=%s leader_norm=%s expected_norm=%s"
            % (
                record.get("host", "<none>"),
                observed_host or "<empty>",
                txt.get("leader", "<missing>") if isinstance(txt, dict) else "<missing>",
                leader_norm or "<empty>",
                expected_norm or "<empty>",
            )
        )

    if require_phase:
        phase = txt.get("phase")
        role = txt.get("role")
        if not phase and not role:
            return "missing TXT phase/role"
        if phase != require_phase and role != require_phase:
            return "phase/role mismatch (phase=%s role=%s)" % (
                phase or "<missing>",
                role or "<missing>",
            )

    if require_role:
        role = txt.get("role")
        if role != require_role:
            return "role mismatch (role=%s)" % (role or "<missing>")

    if expect_addr:
        addr = str(record.get("addr", ""))
        if not addr:
            return "missing IPv4 address"
        if not _ipv4_string(addr):
            return "non-IPv4 address observed (%s)" % addr
        if addr != expect_addr:
            return "IPv4 mismatch observed=%s expected=%s" % (addr, expect_addr)

    return None


def _select_records(
    instance: str,
    service_type: str,
    *,
    runner: Runner,
    domain: str,
) -> List[Dict[str, object]]:
    records = resolve_with_resolvectl(instance, service_type, domain, runner=runner)
    has_txt = any(record.get("txt") for record in records)
    if not records or not has_txt:
        fallback = resolve_with_avahi_browse(service_type, domain, runner=runner)
        if fallback:
            norm_instance = instance.strip().casefold()
            records = [
                record
                for record in fallback
                if record.get("instance", "").strip().casefold() == norm_instance
            ]
    return records


def perform_self_check(
    *,
    instance: str,
    service_type: str,
    domain: str,
    expected_host: str,
    require_phase: Optional[str],
    require_role: Optional[str],
    expect_addr: Optional[str],
    retries: int,
    delay_seconds: float,
    runner: Runner = subprocess.run,
) -> Optional[Dict[str, object]]:
    retries = max(retries, 1)
    expected_norm = norm_host(expected_host)

    for attempt in range(1, retries + 1):
        records = _select_records(
            instance,
            service_type,
            runner=runner,
            domain=domain,
        )

        if not records:
            _log(
                "[mdns-selfcheck] Attempt %d/%d: no records discovered for %s"
                % (attempt, retries, instance)
            )
        for record in records:
            txt = record.get("txt", {})
            if not isinstance(txt, dict):
                txt = {}
            reason = _record_reason(
                record,
                expected_host=expected_host,
                require_phase=require_phase,
                require_role=require_role,
                expect_addr=expect_addr,
            )
            if reason is None:
                host_norm = norm_host(str(record.get("host", "")))
                leader_norm = norm_host(txt.get("leader"))
                _log(
                    "[mdns-selfcheck] Attempt %d/%d: matched host=%s norm=%s leader_norm=%s expected_norm=%s"
                    % (
                        attempt,
                        retries,
                        record.get("host", "<none>"),
                        host_norm or "<empty>",
                        leader_norm or "<empty>",
                        expected_norm or "<empty>",
                    )
                )
                return record

            _log(
                "[mdns-selfcheck] Attempt %d/%d: skipped host=%s reason=%s"
                % (attempt, retries, record.get("host", "<none>"), reason)
            )

        if attempt < retries and delay_seconds > 0:
            _log(
                "[mdns-selfcheck] Attempt %d/%d: retrying in %.3fs"
                % (attempt, retries, delay_seconds)
            )
            time.sleep(delay_seconds)

    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=True)
    parser.add_argument("--type", dest="service_type", required=True)
    parser.add_argument("--domain", default="local")
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--require-phase", choices=["bootstrap", "server"], default=None)
    parser.add_argument("--require-role", default=None)
    parser.add_argument("--expect-addr", default=None)
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--delay-ms", type=int, default=500)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    delay_seconds = max(args.delay_ms, 0) / 1000.0
    record = perform_self_check(
        instance=args.instance,
        service_type=args.service_type,
        domain=args.domain,
        expected_host=args.expected_host,
        require_phase=args.require_phase,
        require_role=args.require_role,
        expect_addr=args.expect_addr or None,
        retries=args.retries,
        delay_seconds=delay_seconds,
    )

    if not record:
        return 1

    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
