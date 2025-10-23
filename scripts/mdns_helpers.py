"""Utilities for normalising and querying sugarkube mDNS advertisements."""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path
from typing import Final, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)


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
    types = [f"_k3s-{cluster}-{environment}._tcp"]
    legacy = "_https._tcp"
    if legacy not in types:
        types.append(legacy)
    return types


def _run_avahi_browse(service_type: str) -> Sequence[str]:
    command = [
        "avahi-browse",
        "--parsable",
        "--terminate",
        "--resolve",
        service_type,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    if not result.stdout:
        return []

    return [line for line in result.stdout.splitlines() if line]


def _load_lines(cluster: str, environment: str) -> Iterable[str]:
    fixture = os.environ.get("SUGARKUBE_MDNS_FIXTURE_FILE")
    if fixture:
        try:
            text = Path(fixture).read_text(encoding="utf-8")
        except OSError:
            return []
        return [line for line in text.splitlines() if line]

    lines: List[str] = []
    for service_type in _service_types(cluster, environment):
        lines.extend(_run_avahi_browse(service_type))
    return lines


def _matches_expected(record: "MdnsRecord", expected: str) -> Tuple[bool, Optional[str]]:
    if _same_host(record.host, expected):
        return True, record.host

    leader = record.txt.get("leader", "")
    if leader and _same_host(leader, expected):
        return True, leader

    return False, None


def ensure_self_ad_is_visible(
    *,
    expected_host: str,
    cluster: str,
    env: str,
    retries: int = 5,
    delay: float = 1.0,
    require_phase: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Return True when the local advert is visible via mDNS."""

    expected_norm = _norm_host(expected_host)
    delay = max(float(delay), 0.0)
    retries = max(int(retries), 1)

    for attempt in range(1, retries + 1):
        lines = _load_lines(cluster, env)
        if lines:
            from k3s_mdns_parser import parse_mdns_records

            records = parse_mdns_records(lines, cluster, env)
        else:
            records = []

        for record in records:
            phase = record.txt.get("phase")
            if require_phase is not None and phase != require_phase:
                continue

            matched, observed = _matches_expected(record, expected_norm)
            if matched:
                return True, observed or record.host

        if attempt != retries:
            time.sleep(delay)

    return False, None


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-host", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--require-phase", choices=["bootstrap", "server"], default=None)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    ok, observed = ensure_self_ad_is_visible(
        expected_host=args.expect_host,
        cluster=args.cluster,
        env=args.env,
        retries=args.retries,
        delay=args.delay,
        require_phase=args.require_phase,
    )

    if ok:
        if observed:
            print(observed)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = ["_norm_host", "_same_host", "ensure_self_ad_is_visible"]
