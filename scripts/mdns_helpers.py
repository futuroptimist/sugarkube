"""Utilities for normalising and comparing mDNS hostnames."""
from __future__ import annotations

import argparse
import subprocess
import time
from typing import TYPE_CHECKING, Callable, Final, Iterable, List, Optional

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)

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

    expect_addr = (expect_addr or "").strip() or None

    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    for attempt in range(1, attempts + 1):
        records = _collect_mdns_records(cluster, env, runner)
        for record in records:
            txt = record.txt
            if require_phase is not None and txt.get("phase") != require_phase:
                continue
            host_match = _same_host(record.host, expected_norm)
            leader_match = _same_host(txt.get("leader", ""), expected_norm)
            if not (host_match or leader_match):
                continue

            if expect_addr:
                record_addr = record.address.strip()
                if (
                    record_addr == expect_addr
                    or txt.get("a") == expect_addr
                    or txt.get("addr") == expect_addr
                ):
                    return record.host
                continue

            return record.host
        if attempt < attempts and delay > 0:
            sleep(delay)
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
