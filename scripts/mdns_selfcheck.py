#!/usr/bin/env python3
"""mDNS/DNS-SD self-check helper for Sugarkube."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from mdns_helpers import norm_host

Record = Dict[str, Any]
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _log(message: str) -> None:
    print(f"{_timestamp()} [mdns-selfcheck] {message}", file=sys.stderr)


def _parse_txt_tokens(payload: str) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    if not payload:
        return txt
    for segment in shlex.split(payload):
        segment = segment.strip()
        if not segment:
            continue
        if segment.lower().startswith("txt="):
            segment = segment[4:]
        if not segment:
            continue
        if "=" in segment:
            key, value = segment.split("=", 1)
        else:
            key, value = segment, ""
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key:
            txt[key] = value
    return txt


def _split_resolvectl_blocks(stdout: str) -> List[List[str]]:
    if not stdout.strip():
        return []
    blocks: List[List[str]] = []
    current: List[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line.rstrip())
    if current:
        blocks.append(current)
    return blocks


def resolve_with_resolvectl(
    instance: str,
    service_type: str,
    domain: str = "local",
    *,
    runner: Optional[Runner] = None,
) -> List[Record]:
    cmd = ["resolvectl", "service", instance, service_type, domain, "--legend=no"]
    runner = runner or subprocess.run
    try:
        result = runner(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []

    stdout = result.stdout or ""
    blocks = _split_resolvectl_blocks(stdout)
    if not blocks:
        return []

    records: List[Record] = []
    for block in blocks:
        record: Record = {
            "instance": instance,
            "type": service_type,
            "domain": domain,
            "host": "",
            "port": 0,
            "addrs": [],
            "addr": "",
            "txt": {},
            "source": "resolvectl",
            "raw": "\n".join(block),
        }
        for line in block:
            stripped = line.strip()
            lowered = stripped.lower()
            if "port" in lowered:
                parts = stripped.replace("=", " ").split()
                for idx, part in enumerate(parts):
                    if part.lower() == "port" and idx + 1 < len(parts):
                        candidate = parts[idx + 1]
                        if candidate.isdigit():
                            record["port"] = int(candidate)
                        break
            if "host" in lowered or "target" in lowered:
                parts = stripped.replace(":", " ").split()
                for idx, part in enumerate(parts):
                    if part.lower() in {"host", "target"} and idx + 1 < len(parts):
                        record["host"] = parts[idx + 1]
                        break
            if any(key in lowered for key in {"address", "ipv4", "ipv6"}):
                for token in stripped.replace(":", " ").split():
                    if token and all(ch in "0123456789abcdefABCDEF:." for ch in token):
                        record["addrs"].append(token)
            if stripped.upper().startswith("TXT"):
                _, _, payload = stripped.partition(":")
                record["txt"].update(_parse_txt_tokens(payload.strip()))
        addrs = record.get("addrs", [])
        ipv4 = next((addr for addr in addrs if addr and ":" not in addr), "")
        record["addr"] = ipv4 or (addrs[0] if addrs else "")
        records.append(record)
    return records


def resolve_with_avahi_browse(
    service_type: str,
    domain: str = "local",
    *,
    runner: Optional[Runner] = None,
) -> List[Record]:
    cmd = ["avahi-browse", "-rptk", service_type, "-d", domain]
    runner = runner or subprocess.run
    try:
        result = runner(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []

    stdout = result.stdout or ""
    records: List[Record] = []
    for line in stdout.splitlines():
        if not line or line[0] not in {"=", "+", "@"}:
            continue
        fields = line.split(";")
        if fields[0] != "=" or len(fields) < 9:
            continue
        instance = fields[3]
        domain_field = fields[5] or domain
        host = fields[6]
        address = fields[7]
        try:
            port = int(fields[8])
        except ValueError:
            port = 0
        txt_fields = {}
        for token in fields[9:]:
            if token.startswith("txt="):
                txt_fields.update(_parse_txt_tokens(token[4:]))
        record: Record = {
            "instance": instance,
            "type": fields[4],
            "domain": domain_field,
            "host": host,
            "port": port,
            "addrs": [address] if address else [],
            "addr": address,
            "txt": txt_fields,
            "source": "avahi-browse",
            "raw": line,
        }
        records.append(record)
    return records


def gather_records(
    instance: str,
    service_type: str,
    domain: str = "local",
    *,
    resolvectl_runner: Optional[Runner] = None,
    avahi_runner: Optional[Runner] = None,
) -> Tuple[List[Record], bool]:
    records = resolve_with_resolvectl(
        instance,
        service_type,
        domain,
        runner=resolvectl_runner,
    )
    if records and any(record["txt"] for record in records):
        return records, False

    fallback = resolve_with_avahi_browse(
        service_type,
        domain,
        runner=avahi_runner,
    )
    instance_norm = norm_host(instance)
    filtered: List[Record] = []
    if instance_norm:
        for record in fallback:
            if norm_host(record.get("instance")) == instance_norm:
                filtered.append(record)
    if filtered:
        return filtered, True
    if fallback:
        return fallback, True
    return records, False


def _ipv4_from_record(record: Record) -> str:
    for addr in record.get("addrs", []):
        if addr and ":" not in addr:
            return addr
    addr = record.get("addr", "")
    if addr and ":" not in addr:
        return addr
    return ""


def run_selfcheck(
    *,
    instance: str,
    service_type: str,
    domain: str = "local",
    expected_host: Optional[str] = None,
    require_phase: Optional[str] = None,
    require_role: Optional[str] = None,
    require_ipv4: bool = False,
    retries: int = 5,
    delay_ms: int = 500,
    resolvectl_runner: Optional[Runner] = None,
    avahi_runner: Optional[Runner] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Tuple[bool, Optional[Record]]:
    retries = max(retries, 1)
    delay_ms = max(delay_ms, 0)
    expected_norm = norm_host(expected_host)

    for attempt in range(1, retries + 1):
        records, used_fallback = gather_records(
            instance,
            service_type,
            domain,
            resolvectl_runner=resolvectl_runner,
            avahi_runner=avahi_runner,
        )
        source = "avahi-browse" if used_fallback else "resolvectl"
        if not records:
            _log(
                f"Attempt {attempt}/{retries}: no records observed via {source}"
            )
            if attempt < retries and delay_ms:
                sleep(delay_ms / 1000.0)
            continue

        _log(
            f"Attempt {attempt}/{retries}: evaluating {len(records)} record(s) from {source}"
        )

        for record in records:
            host_raw = record.get("host", "")
            host_norm = norm_host(host_raw)
            txt = record.get("txt", {})
            if expected_norm and host_norm != expected_norm:
                _log(
                    "Skip instance=%s host=%s (norm=%s) expected=%s (norm=%s): host mismatch"
                    % (
                        record.get("instance", "<unknown>"),
                        host_raw or "<missing>",
                        host_norm or "<missing>",
                        expected_host or "<missing>",
                        expected_norm or "<missing>",
                    )
                )
                continue

            if require_phase:
                phase_val = txt.get("phase")
                if not phase_val:
                    _log(
                        "Skip instance=%s host=%s: missing TXT key 'phase' (keys=%s)"
                        % (
                            record.get("instance", "<unknown>"),
                            host_raw or "<missing>",
                            ",".join(sorted(txt.keys())) or "<none>",
                        )
                    )
                    continue
                if phase_val != require_phase:
                    _log(
                        "Skip instance=%s host=%s: phase mismatch observed=%s expected=%s"
                        % (
                            record.get("instance", "<unknown>"),
                            host_raw or "<missing>",
                            phase_val,
                            require_phase,
                        )
                    )
                    continue

            if require_role:
                role_val = txt.get("role")
                if not role_val:
                    _log(
                        "Skip instance=%s host=%s: missing TXT key 'role' (keys=%s)"
                        % (
                            record.get("instance", "<unknown>"),
                            host_raw or "<missing>",
                            ",".join(sorted(txt.keys())) or "<none>",
                        )
                    )
                    continue
                if role_val != require_role:
                    _log(
                        "Skip instance=%s host=%s: role mismatch observed=%s expected=%s"
                        % (
                            record.get("instance", "<unknown>"),
                            host_raw or "<missing>",
                            role_val,
                            require_role,
                        )
                    )
                    continue

            if require_ipv4:
                ipv4 = _ipv4_from_record(record)
                if not ipv4:
                    _log(
                        "Skip instance=%s host=%s: missing IPv4 address"
                        % (
                            record.get("instance", "<unknown>"),
                            host_raw or "<missing>",
                        )
                    )
                    continue

            return True, record

        if attempt < retries and delay_ms:
            _log(
                f"Attempt {attempt}/{retries}: no records satisfied filters; retrying in {delay_ms / 1000.0:.1f}s"
            )
            sleep(delay_ms / 1000.0)

    return False, None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Sugarkube mDNS advertisements.")
    parser.add_argument("--instance", help="Service instance name to resolve.")
    parser.add_argument(
        "--type", dest="service_type", required=True, help="Service type, e.g. _k3s-*."
    )
    parser.add_argument("--domain", default="local", help="mDNS domain (default: local).")
    parser.add_argument("--expected-host", help="Expected host to match.")
    parser.add_argument("--require-phase", choices=["bootstrap", "server"], help="Required TXT phase value.")
    parser.add_argument("--require-role", help="Required TXT role value.")
    parser.add_argument("--require-ipv4", action="store_true", help="Require an IPv4 address in the record.")
    parser.add_argument("--retries", type=int, default=5, help="Number of attempts to observe the record.")
    parser.add_argument("--delay-ms", type=int, default=500, help="Delay between retries in milliseconds.")
    parser.add_argument("--list", action="store_true", help="List observed records instead of verifying.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.list or not args.instance:
        records = resolve_with_avahi_browse(args.service_type, args.domain)
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0

    success, record = run_selfcheck(
        instance=args.instance,
        service_type=args.service_type,
        domain=args.domain,
        expected_host=args.expected_host,
        require_phase=args.require_phase,
        require_role=args.require_role,
        require_ipv4=args.require_ipv4,
        retries=args.retries,
        delay_ms=args.delay_ms,
    )
    if success and record:
        print(record.get("host", ""))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "gather_records",
    "resolve_with_avahi_browse",
    "resolve_with_resolvectl",
    "run_selfcheck",
]
