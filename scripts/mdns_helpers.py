"""Utilities for normalising and confirming sugarkube mDNS advertisements."""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Final, Iterable, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)

Runner = Callable[..., subprocess.CompletedProcess[str]]


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


def _service_types(cluster: str, environment: str) -> Sequence[str]:
    service = f"_k3s-{cluster}-{environment}._tcp"
    types = [service]
    legacy = "_https._tcp"
    if legacy not in types:
        types.append(legacy)
    return types


def _browse_once(service_type: str, *, runner: Runner) -> Iterable[str]:
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
    if result.stdout:
        return [line for line in result.stdout.splitlines() if line]
    return []


def _load_lines(cluster: str, environment: str, *, runner: Optional[Runner] = None) -> List[str]:
    fixture_path = os.environ.get("SUGARKUBE_MDNS_FIXTURE_FILE")
    if fixture_path:
        try:
            text = Path(fixture_path).read_text(encoding="utf-8")
        except OSError:
            return []
        return [line for line in text.splitlines() if line]

    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    lines: List[str] = []
    for service_type in _service_types(cluster, environment):
        lines.extend(_browse_once(service_type, runner=runner))
    return lines


def _find_records(
    cluster: str,
    environment: str,
    *,
    runner: Optional[Runner] = None,
) -> List["MdnsRecord"]:
    lines = _load_lines(cluster, environment, runner=runner)
    if not lines:
        return []
    from k3s_mdns_parser import parse_mdns_records  # Local import to avoid circular dependency

    return parse_mdns_records(lines, cluster, environment)


def ensure_self_ad_is_visible(
    *,
    expected_host: str,
    cluster: str,
    env: str,
    retries: int = 5,
    delay: float = 1.0,
    require_phase: Optional[str] = None,
    runner: Optional[Runner] = None,
) -> Optional[Tuple[str, int]]:
    """Confirm that the expected host advertises itself via mDNS."""

    expected_norm = _norm_host(expected_host)
    for attempt in range(1, retries + 1):
        for record in _find_records(cluster, env, runner=runner):
            if require_phase is not None and record.txt.get("phase") != require_phase:
                continue

            host_match = _same_host(record.host, expected_norm)
            leader_match = _same_host(record.txt.get("leader", ""), expected_norm)
            if host_match or leader_match:
                observed = record.host if host_match else record.txt.get("leader", record.host)
                return observed or record.host, attempt

        time.sleep(delay)

    return None


def _main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-host", required=True)
    ap.add_argument("--cluster", required=True)
    ap.add_argument("--env", required=True)
    ap.add_argument("--require-phase", choices=["bootstrap", "server"], default=None)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args(argv)

    result = ensure_self_ad_is_visible(
        expected_host=args.expect_host,
        cluster=args.cluster,
        env=args.env,
        retries=args.retries,
        delay=args.delay,
        require_phase=args.require_phase,
    )
    if result is None:
        return 1

    observed, attempt = result
    print(f"observed={observed} attempt={attempt}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI exercised in tests
    raise SystemExit(_main())


__all__ = ["_norm_host", "_same_host", "ensure_self_ad_is_visible"]
