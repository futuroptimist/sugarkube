"""Utilities for normalising and verifying mDNS advertisements."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Final, Iterable, List, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)
_LEGACY_SERVICE: Final = "_https._tcp"


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
    service = f"_k3s-{cluster}-{environment}._tcp"
    if service == _LEGACY_SERVICE:
        return [service]
    return [service, _LEGACY_SERVICE]


def _load_lines_from_fixture(fixture_path: str) -> Iterable[str]:
    try:
        text = Path(fixture_path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line for line in text.splitlines() if line]


def _run_avahi(
    command: List[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, returncode=127, stdout="", stderr="")


def _load_lines_from_avahi(
    cluster: str,
    environment: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> Iterable[str]:
    lines: List[str] = []
    for service_type in _service_types(cluster, environment):
        command = [
            "avahi-browse",
            "--parsable",
            "--terminate",
            "--resolve",
            service_type,
        ]
        result = _run_avahi(command, runner)
        if result.returncode == 0 and result.stdout:
            lines.extend(line for line in result.stdout.splitlines() if line)
        elif result.stdout:
            lines.extend(line for line in result.stdout.splitlines() if line)
    return lines


def _discover_records(
    cluster: str,
    environment: str,
    *,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    fixture_path: Optional[str] = None,
) -> List["MdnsRecord"]:
    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    if fixture_path:
        lines = _load_lines_from_fixture(fixture_path)
    else:
        lines = _load_lines_from_avahi(cluster, environment, runner)

    from k3s_mdns_parser import parse_mdns_records

    return parse_mdns_records(lines, cluster, environment)


def ensure_self_ad_is_visible(
    expected_host: str,
    cluster: str,
    env: str,
    *,
    retries: int = 5,
    delay: float = 1.0,
    require_phase: Optional[str] = None,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    fixture_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Return ``(True, host)`` when the expected advertisement becomes visible."""

    expected_norm = _norm_host(expected_host)
    last_observed = ""

    for _ in range(max(retries, 1)):
        records = _discover_records(
            cluster,
            env,
            runner=runner,
            fixture_path=fixture_path,
        )
        for record in records:
            leader = record.txt.get("leader", "")
            phase_ok = require_phase is None or record.txt.get("phase") == require_phase
            if not phase_ok:
                if record.host:
                    last_observed = record.host
                elif leader:
                    last_observed = leader
                continue

            if _same_host(record.host, expected_norm):
                return True, record.host
            if leader and _same_host(leader, expected_norm):
                return True, leader

            if record.host:
                last_observed = record.host
            elif leader:
                last_observed = leader

        time.sleep(delay)

    return False, last_observed


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-host", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--require-phase", choices=["bootstrap", "server"], default=None)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    fixture_path = os.environ.get("SUGARKUBE_MDNS_FIXTURE_FILE")

    ok, observed = ensure_self_ad_is_visible(
        expected_host=args.expect_host,
        cluster=args.cluster,
        env=args.env,
        retries=args.retries,
        delay=args.delay,
        require_phase=args.require_phase,
        fixture_path=fixture_path,
    )

    if ok:
        if observed:
            print(observed)
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = ["_norm_host", "_same_host", "ensure_self_ad_is_visible"]
