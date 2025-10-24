"""Utilities for normalising and comparing mDNS hostnames."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Callable, Final, Iterable, List, Optional

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)
_PHASE_TO_ROLE: Final = {
    "bootstrap": "bootstrap",
    "server": "server",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]
SleepFn = Callable[[float], None]


def _norm_host(host: str) -> str:
    """Normalise a hostname for comparison."""

    host = host.strip()
    if not host:
        return ""

    while host.endswith("."):
        host = host[:-1]

    return host.lower()


def _strip_local_suffix(host: str) -> str:
    for suffix in _LOCAL_SUFFIXES:
        if host.endswith(suffix):
            return host[: -len(suffix)]
    return host


def _same_host(left: str, right: str) -> bool:
    """Return True when two hosts refer to the same machine."""

    left_norm = _norm_host(left)
    right_norm = _norm_host(right)
    if not left_norm or not right_norm:
        return False

    if left_norm == right_norm:
        return True

    return _strip_local_suffix(left_norm) == _strip_local_suffix(right_norm)


def _service_types(cluster: str, environment: str) -> List[str]:
    service_type = f"_k3s-{cluster}-{environment}._tcp"
    types = [service_type]
    legacy = "_https._tcp"
    if legacy not in types:
        types.append(legacy)
    return types


def _browse_service_type(
    service_type: str, runner: Runner
) -> Iterable[str]:
    command = [
        "avahi-browse",
        "--parsable",
        "--terminate",
        "--resolve",
        service_type,
    ]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    stdout = result.stdout if result.stdout else ""
    return [line for line in stdout.splitlines() if line]


def _collect_mdns_records(
    cluster: str,
    environment: str,
    runner: Runner,
) -> List["MdnsRecord"]:
    from k3s_mdns_parser import parse_mdns_records
    lines: List[str] = []
    for service_type in _service_types(cluster, environment):
        lines.extend(_browse_service_type(service_type, runner))
    if not lines:
        return []
    return parse_mdns_records(lines, cluster, environment)


def ensure_self_ad_is_visible(
    *,
    expected_host: str,
    cluster: str,
    env: str,
    retries: int = 5,
    delay: float = 1.0,
    require_phase: Optional[str] = None,
    expect_addr: Optional[str] = None,
    runner: Optional[Runner] = None,
    sleep: SleepFn = time.sleep,
) -> Optional[str]:
    """Return the observed host when the local advertisement is visible."""

    expected_norm = _norm_host(expected_host)
    if not expected_norm:
        return None

    attempts = max(retries, 1)
    delay = max(delay, 0.0)

    required_phase = (require_phase or "").strip().lower() or None
    expected_role_for_phase = _PHASE_TO_ROLE.get(required_phase or "")

    expect_addr = (expect_addr or "").strip() or None

    fallback_candidate: Optional[str] = None
    fallback_addr: Optional[str] = None
    host_only_candidate: Optional[str] = None

    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    for attempt in range(1, attempts + 1):
        records = _collect_mdns_records(cluster, env, runner)
        for record in records:
            txt = record.txt
            if required_phase is not None:
                phase_value = txt.get("phase", "").strip().lower()
                if phase_value != required_phase:
                    role_value = txt.get("role", "").strip().lower()
                    if not (phase_value == "" and role_value == expected_role_for_phase):
                        continue
            host_match = _same_host(record.host, expected_norm)
            leader_match = _same_host(txt.get("leader", ""), expected_norm)
            if not (host_match or leader_match):
                continue

            if expect_addr:
                record_addr = record.address.strip()
                txt_addr = txt.get("a", "").strip()
                txt_addr_alt = txt.get("addr", "").strip()
                observed_addrs = [
                    addr for addr in (record_addr, txt_addr, txt_addr_alt) if addr
                ]
                if expect_addr in observed_addrs:
                    return record.host

                if fallback_candidate is None and observed_addrs:
                    has_ipv4 = any("." in addr and ":" not in addr for addr in observed_addrs)
                    has_ipv6 = any(":" in addr for addr in observed_addrs)
                    if has_ipv6 and not has_ipv4:
                        fallback_candidate = record.host
                        fallback_addr = observed_addrs[0]
                if not observed_addrs and host_only_candidate is None:
                    host_only_candidate = record.host
                continue

            return record.host
        if attempt < attempts and delay > 0:
            sleep(delay)

    if fallback_candidate and expect_addr:
        mismatch = fallback_addr or "<unknown>"
        print(
            (
                "[k3s-discover mdns] WARN: expected IPv4 %s for %s but "
                "observed %s; assuming match after %d attempts"
            )
            % (expect_addr, expected_norm, mismatch, attempts),
            file=sys.stderr,
        )
        return fallback_candidate

    if host_only_candidate and expect_addr:
        print(
            (
                "[k3s-discover mdns] WARN: expected IPv4 %s for %s but "
                "advertisement omitted address; assuming match after %d attempts"
            )
            % (expect_addr, expected_norm, attempts),
            file=sys.stderr,
        )
        return host_only_candidate

    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-host", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--require-phase", choices=["bootstrap", "server"], default=None)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--expect-addr", default=None)
    return parser


def _main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    observed = ensure_self_ad_is_visible(
        expected_host=args.expect_host,
        cluster=args.cluster,
        env=args.env,
        retries=args.retries,
        delay=args.delay,
        require_phase=args.require_phase,
        expect_addr=args.expect_addr,
    )
    if observed:
        print(observed)
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())


__all__ = ["_norm_host", "_same_host", "ensure_self_ad_is_visible"]
