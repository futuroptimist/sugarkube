#!/usr/bin/env python3
"""Resolve k3s mDNS advertisements and verify their TXT metadata."""
from __future__ import annotations

import argparse
import ipaddress
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from mdns_helpers import norm_host


Runner = Callable[..., subprocess.CompletedProcess[str]]
Record = Dict[str, object]


@dataclass
class TimestampedLogger:
    stderr: Optional[object] = None

    def _stream(self) -> object:
        return self.stderr if self.stderr is not None else sys.stderr

    @staticmethod
    def _timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    def log(self, message: str) -> None:
        print(f"{self._timestamp()} {message}", file=self._stream())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_txt_tokens(tokens: Iterable[str]) -> Dict[str, str]:
    txt: Dict[str, str] = {}
    for token in tokens:
        if not token:
            continue
        entry = token.strip()
        if not entry:
            continue
        fragments = [fragment.strip() for fragment in entry.split(",") if fragment.strip()]
        if not fragments:
            fragments = [entry]
        for fragment in fragments:
            item = fragment
            if item.lower().startswith("txt="):
                item = item[4:]
            if "=" in item:
                key, value = item.split("=", 1)
            else:
                key, value = item, ""
            key = _strip_quotes(key.strip()).lower()
            value = _strip_quotes(value.strip())
            if key:
                txt[key] = value
    return txt


def resolve_with_resolvectl(
    instance: str,
    service_type: str,
    *,
    domain: str = "local",
    runner: Optional[Runner] = None,
) -> List[Record]:
    """Resolve a service instance via ``resolvectl service``."""

    command = ["resolvectl", "service", instance, service_type, domain, "--legend=no"]
    executor = runner or subprocess.run
    try:
        result = executor(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    stdout = result.stdout or ""
    if not stdout.strip():
        return []

    records: List[Record] = []
    current: Optional[Record] = None

    def ensure_current() -> Record:
        nonlocal current
        if current is None:
            current = {
                "instance": instance,
                "type": service_type,
                "domain": domain,
                "host": "",
                "addr": "",
                "port": None,
                "txt": {},
                "raw": [],
                "addresses": [],
            }
        return current

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current is not None:
                current["raw"] = "\n".join(current["raw"])  # type: ignore[index]
                records.append(current)
                current = None
            continue

        record = ensure_current()
        record["raw"].append(raw_line)  # type: ignore[index]
        lower = line.lower()

        if lower.startswith("txt"):
            payload = ""
            if ":" in line:
                payload = line.split(":", 1)[1].strip()
            elif " " in line:
                payload = line.split(None, 1)[1].strip()
            tokens = shlex.split(payload) if payload else []
            txt_values = _parse_txt_tokens(tokens)
            if txt_values:
                record_txt = record["txt"]  # type: ignore[assignment]
                record_txt.update(txt_values)
            continue

        if any(lower.startswith(prefix) for prefix in ("target", "host")):
            if "=" in line:
                record["host"] = line.split("=", 1)[1].strip()
            elif " " in line:
                record["host"] = line.split(None, 1)[1].strip()
            continue

        if ":" in line and not line.startswith(";;"):
            host_candidate, _, remainder = line.partition(":")
            port_token = remainder.strip().split()[0] if remainder.strip() else ""
            if port_token.isdigit():
                record["host"] = host_candidate.strip()
                record["port"] = int(port_token)

        for token in line.replace("=", " ").replace(",", " ").split():
            candidate = token.strip("[]")
            try:
                ip_obj = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            addresses: List[str] = record["addresses"]  # type: ignore[assignment]
            addresses.append(str(ip_obj))
            addr = record.get("addr", "")
            if ip_obj.version == 4 or not addr:
                record["addr"] = str(ip_obj)

    if current is not None:
        current["raw"] = "\n".join(current["raw"])  # type: ignore[index]
        records.append(current)

    for record in records:
        if isinstance(record.get("raw"), list):
            record["raw"] = "\n".join(record["raw"])  # type: ignore[index]
    return records


def _parse_avahi_line(line: str) -> Optional[Record]:
    if not line or line[0] != "=":
        return None
    fields = line.split(";")
    if len(fields) < 9:
        return None

    instance = _strip_quotes(fields[3])
    service_type = fields[4]
    domain = fields[5] or "local"
    host = _strip_quotes(fields[6])
    addr = _strip_quotes(fields[7])
    port_field = fields[8]
    try:
        port = int(port_field)
    except ValueError:
        port = None

    txt = _parse_txt_tokens(field for field in fields[9:] if field.startswith("txt="))
    record: Record = {
        "instance": instance,
        "type": service_type,
        "domain": domain,
        "host": host,
        "addr": addr,
        "port": port,
        "txt": txt,
        "raw": line,
    }
    addresses: List[str] = []
    if addr:
        addresses.append(addr)
    record["addresses"] = addresses
    return record


def resolve_with_avahi_browse(
    service_type: str,
    *,
    domain: str = "local",
    runner: Optional[Runner] = None,
) -> List[Record]:
    """Resolve service records using ``avahi-browse``."""

    command = ["avahi-browse", "-rptk", service_type, "-d", domain]
    executor = runner or subprocess.run
    try:
        result = executor(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    stdout = result.stdout or ""
    records: List[Record] = []
    for line in stdout.splitlines():
        if not line:
            continue
        record = _parse_avahi_line(line)
        if record is not None:
            records.append(record)
    return records


def _has_txt(records: Sequence[Record]) -> bool:
    for record in records:
        txt = record.get("txt")
        if isinstance(txt, dict) and txt:
            return True
    return False


def gather_records(
    *,
    instance: str,
    service_type: str,
    domain: str,
    resolvectl_runner: Optional[Runner],
    avahi_runner: Optional[Runner],
    logger: Optional[TimestampedLogger],
) -> List[Record]:
    records = resolve_with_resolvectl(
        instance,
        service_type,
        domain=domain,
        runner=resolvectl_runner,
    )
    if records and _has_txt(records):
        return records

    if logger is not None:
        logger.log(
            "[mdns-selfcheck] resolvectl did not return TXT data; falling back to avahi-browse"
        )

    fallback = resolve_with_avahi_browse(
        service_type,
        domain=domain,
        runner=avahi_runner,
    )
    instance_norm = norm_host(instance)
    filtered: List[Record] = []
    for record in fallback:
        observed = norm_host(str(record.get("instance", "")))
        if observed == instance_norm:
            filtered.append(record)
    return filtered


def _match_host(record: Record, expected_host: str) -> bool:
    if not expected_host:
        return True
    host = str(record.get("host", ""))
    host_norm = norm_host(host)
    expected_norm = norm_host(expected_host)
    if host_norm == expected_norm:
        return True

    txt = record.get("txt")
    if isinstance(txt, dict):
        leader = norm_host(str(txt.get("leader", "")))
        if leader and leader == expected_norm:
            return True
    return False


def _log_host_mismatch(
    record: Record,
    expected_host: str,
    logger: Optional[TimestampedLogger],
    attempt: int,
    retries: int,
) -> None:
    if logger is None or not expected_host:
        return
    host = str(record.get("host", ""))
    txt = record.get("txt") if isinstance(record.get("txt"), dict) else {}
    leader = ""
    if isinstance(txt, dict):
        leader = str(txt.get("leader", ""))
    message = (
        "[mdns-selfcheck] Attempt %d/%d: skipped instance %s due to host mismatch "
        "(host raw='%s' norm='%s', leader raw='%s' norm='%s', expected raw='%s' norm='%s')"
        % (
            attempt,
            retries,
            record.get("instance", ""),
            host or "<missing>",
            norm_host(host) or "<empty>",
            leader or "<missing>",
            norm_host(leader) or "<empty>",
            expected_host,
            norm_host(expected_host) or "<empty>",
        )
    )
    logger.log(message)


def _log_phase_issue(
    *,
    record: Record,
    required_phase: Optional[str],
    required_role: Optional[str],
    logger: Optional[TimestampedLogger],
    attempt: int,
    retries: int,
) -> None:
    if logger is None:
        return
    txt = record.get("txt") if isinstance(record.get("txt"), dict) else {}
    phase = txt.get("phase", "<missing>") if isinstance(txt, dict) else "<missing>"
    role = txt.get("role", "<missing>") if isinstance(txt, dict) else "<missing>"
    logger.log(
        "[mdns-selfcheck] Attempt %d/%d: skipped instance %s due to phase/role mismatch "
        "(required phase=%s role=%s, observed phase=%s role=%s)"
        % (
            attempt,
            retries,
            record.get("instance", ""),
            required_phase or "<any>",
            required_role or "<any>",
            phase,
            role,
        )
    )


def _log_address_issue(
    *,
    record: Record,
    expected_addr: str,
    require_ipv4: bool,
    logger: Optional[TimestampedLogger],
    attempt: int,
    retries: int,
) -> None:
    if logger is None:
        return
    addr = str(record.get("addr", ""))
    addresses = record.get("addresses", [])
    if isinstance(addresses, list) and addresses:
        observed = ", ".join(addresses)
    else:
        observed = addr or "<missing>"
    logger.log(
        "[mdns-selfcheck] Attempt %d/%d: skipped instance %s due to address mismatch "
        "(expected=%s require_ipv4=%s observed=%s)"
        % (
            attempt,
            retries,
            record.get("instance", ""),
            expected_addr or "<none>",
            "yes" if require_ipv4 else "no",
            observed,
        )
    )


def select_record(
    records: Sequence[Record],
    *,
    expected_host: str,
    required_phase: Optional[str],
    required_role: Optional[str],
    expected_addr: str,
    require_ipv4: bool,
    logger: Optional[TimestampedLogger],
    attempt: int,
    retries: int,
) -> Optional[Record]:
    for record in records:
        if expected_host and not _match_host(record, expected_host):
            _log_host_mismatch(record, expected_host, logger, attempt, retries)
            continue

        txt = record.get("txt") if isinstance(record.get("txt"), dict) else {}
        phase = txt.get("phase") if isinstance(txt, dict) else None
        role = txt.get("role") if isinstance(txt, dict) else None

        if required_phase and phase != required_phase:
            _log_phase_issue(
                record=record,
                required_phase=required_phase,
                required_role=required_role,
                logger=logger,
                attempt=attempt,
                retries=retries,
            )
            continue

        if required_role and role != required_role:
            _log_phase_issue(
                record=record,
                required_phase=required_phase,
                required_role=required_role,
                logger=logger,
                attempt=attempt,
                retries=retries,
            )
            continue

        addr = str(record.get("addr", ""))
        if expected_addr and addr != expected_addr:
            _log_address_issue(
                record=record,
                expected_addr=expected_addr,
                require_ipv4=require_ipv4,
                logger=logger,
                attempt=attempt,
                retries=retries,
            )
            continue

        if require_ipv4:
            try:
                ip_obj = ipaddress.ip_address(addr)
            except ValueError:
                _log_address_issue(
                    record=record,
                    expected_addr=expected_addr,
                    require_ipv4=require_ipv4,
                    logger=logger,
                    attempt=attempt,
                    retries=retries,
                )
                continue
            if ip_obj.version != 4:
                _log_address_issue(
                    record=record,
                    expected_addr=expected_addr,
                    require_ipv4=require_ipv4,
                    logger=logger,
                    attempt=attempt,
                    retries=retries,
                )
                continue

        return record
    return None


def run_selfcheck(
    *,
    instance: str,
    service_type: str,
    domain: str,
    expected_host: str,
    required_phase: Optional[str],
    required_role: Optional[str],
    expected_addr: str,
    require_ipv4: bool,
    retries: int,
    delay: float,
    resolvectl_runner: Optional[Runner] = None,
    avahi_runner: Optional[Runner] = None,
    logger: Optional[TimestampedLogger] = None,
) -> Optional[Record]:
    attempts = max(retries, 1)
    delay = max(delay, 0.0)
    active_logger = logger or TimestampedLogger()

    for attempt in range(1, attempts + 1):
        records = gather_records(
            instance=instance,
            service_type=service_type,
            domain=domain,
            resolvectl_runner=resolvectl_runner,
            avahi_runner=avahi_runner,
            logger=active_logger,
        )

        if not records:
            active_logger.log(
                "[mdns-selfcheck] Attempt %d/%d: no records discovered for instance %s type %s"
                % (attempt, attempts, instance, service_type)
            )
        else:
            active_logger.log(
                "[mdns-selfcheck] Attempt %d/%d: discovered %d record(s)"
                % (attempt, attempts, len(records))
            )
            match = select_record(
                records,
                expected_host=expected_host,
                required_phase=required_phase,
                required_role=required_role,
                expected_addr=expected_addr,
                require_ipv4=require_ipv4,
                logger=active_logger,
                attempt=attempt,
                retries=attempts,
            )
            if match is not None:
                return match

        if attempt < attempts and delay > 0:
            active_logger.log(
                "[mdns-selfcheck] Attempt %d/%d did not match filters; retrying in %.2fs"
                % (attempt, attempts, delay)
            )
            time.sleep(delay)

    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--type", dest="service_type", required=True)
    parser.add_argument("--domain", default="local")
    parser.add_argument("--expected-host", default="")
    parser.add_argument("--expected-addr", default="")
    parser.add_argument("--require-phase", default=None)
    parser.add_argument("--require-role", default=None)
    parser.add_argument("--require-ipv4", action="store_true")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--delay-ms", type=float, default=500.0)
    parser.add_argument("--print-json", action="store_true")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    logger = TimestampedLogger()
    match = run_selfcheck(
        instance=args.instance,
        service_type=args.service_type,
        domain=args.domain,
        expected_host=args.expected_host,
        required_phase=args.require_phase,
        required_role=args.require_role,
        expected_addr=args.expected_addr,
        require_ipv4=args.require_ipv4,
        retries=args.retries,
        delay=args.delay_ms / 1000.0,
        logger=logger,
    )

    if match is None:
        return 1

    if args.print_json:
        import json

        safe_match = {
            "instance": match.get("instance"),
            "type": match.get("type"),
            "domain": match.get("domain"),
            "host": match.get("host"),
            "addr": match.get("addr"),
            "port": match.get("port"),
            "txt": match.get("txt"),
        }
        print(json.dumps(safe_match, indent=2))
    else:
        print(match.get("host", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "gather_records",
    "resolve_with_avahi_browse",
    "resolve_with_resolvectl",
    "run_selfcheck",
    "select_record",
]
