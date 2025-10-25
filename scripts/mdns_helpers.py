"""Utilities for normalising and comparing mDNS hostnames."""
from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Final, Iterable, List, Optional

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)


def _determine_browse_timeout() -> float:
    raw = os.environ.get("SUGARKUBE_MDNS_BROWSE_TIMEOUT", "")
    if not raw:
        return 5.0
    try:
        value = float(raw)
    except ValueError:
        return 5.0
    return value if value > 0 else 5.0


_DEFAULT_BROWSE_TIMEOUT: Final[float] = _determine_browse_timeout()

Runner = Callable[..., subprocess.CompletedProcess[str]]
SleepFn = Callable[[float], None]


@dataclass(frozen=True)
class BrowseTimeout(RuntimeError):
    """Raised when avahi-browse exceeds the configured timeout."""

    service_type: str
    duration: float


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
        while host.endswith(suffix):
            host = host[: -len(suffix)]
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
    service_type: str,
    runner: Runner,
    *,
    resolve: bool = True,
    timeout: float = _DEFAULT_BROWSE_TIMEOUT,
) -> Iterable[str]:
    command = [
        "avahi-browse",
        "--parsable",
        "--terminate",
    ]
    if resolve:
        command.append("--resolve")
    command.append(service_type)
    kwargs = {
        "capture_output": True,
        "text": True,
        "check": False,
    }

    # Only pass a timeout when we are using subprocess.run directly, so that
    # test doubles do not need to implement the parameter. Custom runners may
    # still honour the timeout via **kwargs if they wish.
    if runner is subprocess.run and timeout > 0:
        kwargs["timeout"] = timeout

    try:
        result = runner(command, **kwargs)
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired as exc:
        duration = exc.timeout if isinstance(exc.timeout, (int, float)) else timeout
        print(
            (
                "[k3s-discover mdns] WARN: avahi-browse timed out after %.1fs "
                "while resolving %s"
            )
            % (duration, service_type),
            file=sys.stderr,
        )
        raise BrowseTimeout(service_type, float(duration) if duration else timeout)
    except TypeError:
        # Some tests inject lightweight runners that do not accept a timeout
        # parameter. Retry without the optional kwargs in that scenario.
        kwargs.pop("timeout", None)
        result = runner(command, **kwargs)

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
        try:
            lines.extend(
                _browse_service_type(
                    service_type,
                    runner,
                    resolve=True,
                    timeout=_DEFAULT_BROWSE_TIMEOUT,
                )
            )
        except BrowseTimeout:
            raise

    records = parse_mdns_records(lines, cluster, environment)
    if records:
        return records

    fallback_lines: List[str] = []
    for service_type in _service_types(cluster, environment):
        try:
            fallback_lines.extend(
                _browse_service_type(
                    service_type,
                    runner,
                    resolve=False,
                    timeout=_DEFAULT_BROWSE_TIMEOUT,
                )
            )
        except BrowseTimeout:
            raise
    if not fallback_lines:
        return []

    return parse_mdns_records(fallback_lines, cluster, environment)


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
    max_attempts = attempts
    timeouts_seen = 0
    delay = max(delay, 0.0)

    expect_addr = (expect_addr or "").strip() or None

    fallback_candidate: Optional[str] = None
    fallback_addr: Optional[str] = None
    host_only_candidate: Optional[str] = None
    host_only_value: Optional[str] = None

    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    attempt = 1
    while attempt <= max_attempts:
        try:
            records = _collect_mdns_records(cluster, env, runner)
        except BrowseTimeout:
            timeouts_seen += 1
            if timeouts_seen == 1:
                max_attempts = min(max_attempts, attempt + 2)
            if attempt >= max_attempts:
                break
            attempt += 1
            if attempt <= max_attempts and delay > 0:
                sleep(delay)
            continue
        for record in records:
            txt = record.txt

            phase = txt.get("phase")
            role = txt.get("role")
            if require_phase is not None:
                phase_matches = phase == require_phase
                role_matches = role == require_phase if role else False
                if not (phase_matches or (phase is None and role_matches)):
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

                categories = []
                for candidate in observed_addrs:
                    try:
                        ip_obj = ipaddress.ip_address(candidate)
                    except ValueError:
                        categories.append("other")
                    else:
                        categories.append("ipv4" if ip_obj.version == 4 else "ipv6")

                has_ipv4 = "ipv4" in categories
                has_ipv6 = "ipv6" in categories
                has_other = "other" in categories

                if fallback_candidate is None and has_ipv6 and not has_ipv4:
                    fallback_candidate = record.host
                    for candidate, category in zip(observed_addrs, categories):
                        if category == "ipv6":
                            fallback_addr = candidate
                            break
                if host_only_candidate is None and (
                    not observed_addrs or (has_other and not has_ipv4 and not has_ipv6)
                ):
                    host_only_candidate = record.host
                    host_only_value = observed_addrs[0] if observed_addrs else None
                continue

            return record.host
        if attempt < max_attempts and delay > 0:
            sleep(delay)
        attempt += 1

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
        if host_only_value:
            message = (
                "[k3s-discover mdns] WARN: expected IPv4 %s for %s but "
                "advertisement reported non-IP %s; assuming match after %d attempts"
            ) % (expect_addr, expected_norm, host_only_value, attempts)
        else:
            message = (
                "[k3s-discover mdns] WARN: expected IPv4 %s for %s but "
                "advertisement omitted address; assuming match after %d attempts"
            ) % (expect_addr, expected_norm, attempts)
        print(message, file=sys.stderr)
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
