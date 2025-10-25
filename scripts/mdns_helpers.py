"""Utilities for normalising and comparing mDNS hostnames."""
from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
import sys
import time
from typing import (
    TYPE_CHECKING,
    Callable,
    Final,
    Iterable,
    List,
    Mapping,
    Optional,
    TextIO,
)

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from k3s_mdns_parser import MdnsRecord

_LOCAL_SUFFIXES: Final = (".local",)
_CONTROL_CHAR_MAP: Final = {i: None for i in range(32)}
_CONTROL_CHAR_MAP.update({0x7F: None})


def norm_host(host: Optional[str]) -> str:
    """Return a lowercase hostname without a trailing dot."""

    return (host or "").rstrip(".").lower()


def _determine_browse_timeout() -> float:
    raw = os.environ.get("SUGARKUBE_MDNS_BROWSE_TIMEOUT", "")
    if not raw:
        return 1.5
    try:
        value = float(raw)
    except ValueError:
        return 1.5
    return value if value > 0 else 1.5


_DEFAULT_BROWSE_TIMEOUT: Final[float] = _determine_browse_timeout()

Runner = Callable[..., subprocess.CompletedProcess[str]]
SleepFn = Callable[[float], None]


class _TimestampedLogger:
    """Emit timestamped log lines to the requested streams."""

    def __init__(
        self,
        *,
        stderr: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None,
    ) -> None:
        self._stderr = stderr
        self._stdout = stdout

    @staticmethod
    def _timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    def err(self, message: str) -> None:
        stream = self._stderr if self._stderr is not None else sys.stderr
        print(f"{self._timestamp()} {message}", file=stream)

    def out(self, message: str) -> None:
        stream = self._stdout if self._stdout is not None else sys.stdout
        print(f"{self._timestamp()} {message}", file=stream)


_LOGGER = _TimestampedLogger()


def _log(message: str) -> None:
    _LOGGER.err(message)


def normalize_hostname(host: str) -> str:
    """Return a case-insensitive, dot-normalised hostname."""

    if not host:
        return ""

    candidate = host.translate(_CONTROL_CHAR_MAP).strip()
    if not candidate:
        return ""

    return norm_host(candidate)


def _norm_host(host: str) -> str:
    """Backwards-compatible alias for ``normalize_hostname``."""

    return normalize_hostname(host)


def _strip_local_suffix(host: str) -> str:
    for suffix in _LOCAL_SUFFIXES:
        while host.endswith(suffix):
            host = host[: -len(suffix)]
    return host


def _same_host(left: str, right: str) -> bool:
    """Return True when two hosts refer to the same machine."""

    left_norm = normalize_hostname(left)
    right_norm = normalize_hostname(right)
    if not left_norm or not right_norm:
        return False

    if left_norm == right_norm:
        return True

    return _strip_local_suffix(left_norm) == _strip_local_suffix(right_norm)


def build_publish_cmd(
    *,
    instance: str,
    service_type: str,
    port: int,
    host: Optional[str],
    txt: Mapping[str, str],
) -> List[str]:
    """Construct an ``avahi-publish`` command with discrete TXT arguments."""

    command: List[str] = ["avahi-publish", "-s"]
    if host:
        command.extend(["-H", host])

    command.extend([instance, service_type, str(port)])

    if txt:
        for key, value in txt.items():
            command.append(f"{key}={value}")

    return command


def build_publish_command(
    *,
    instance: str,
    service_type: str,
    port: int,
    host: Optional[str],
    txt: Mapping[str, str],
) -> List[str]:
    """Legacy alias for :func:`build_publish_cmd`."""

    return build_publish_cmd(
        instance=instance,
        service_type=service_type,
        port=port,
        host=host,
        txt=txt,
    )


def _service_types(cluster: str, environment: str) -> List[str]:
    service_type = f"_k3s-{cluster}-{environment}._tcp"
    types = [service_type]
    legacy = "_https._tcp"
    if legacy not in types:
        types.append(legacy)
    return types


def _categorise_addresses(addresses: Iterable[str]) -> List[str]:
    categories: List[str] = []
    for candidate in addresses:
        try:
            ip_obj = ipaddress.ip_address(candidate)
        except ValueError:
            categories.append("other")
        else:
            categories.append("ipv4" if ip_obj.version == 4 else "ipv6")
    return categories


def _describe_addr_mismatch(
    expect_addr: str, observed_addrs: List[str], categories: List[str]
) -> str:
    if not observed_addrs:
        return (
            "Advertisement omitted addresses. Avahi may still be initialising or publishing via "
            "another interface."
        )

    ipv4 = sorted({addr for addr, cat in zip(observed_addrs, categories) if cat == "ipv4"})
    ipv6 = sorted({addr for addr, cat in zip(observed_addrs, categories) if cat == "ipv6"})
    other = sorted({addr for addr, cat in zip(observed_addrs, categories) if cat == "other"})

    if ipv4 and expect_addr not in ipv4:
        return (
            "Advertisement reported IPv4 address(es) %s that do not include expected %s. "
            "Multiple interfaces (e.g. wlan0 vs eth0) or stale Avahi cache entries are likely."
        ) % (", ".join(ipv4), expect_addr)

    if not ipv4 and ipv6:
        return (
            "Advertisement only reported IPv6 address(es) %s. Ensure IPv4 is configured or allow IPv6 discovery."
        ) % (", ".join(ipv6))

    if other:
        return (
            "Advertisement reported non-IP address value(s) %s. Verify avahi-publish-address advertises IPv4."
        ) % (", ".join(other))

    return "Advertisement addresses did not match the expected value."


def _browse_service_type(
    service_type: str,
    runner: Runner,
    *,
    resolve: bool = True,
    timeout: float = _DEFAULT_BROWSE_TIMEOUT,
) -> Iterable[str]:
    command: List[str] = ["avahi-browse"]
    flag = "-ptk"
    if resolve:
        flag = "-rptk"
    command.extend([flag, service_type])
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
        _log(
            (
                "[k3s-discover mdns] WARN: avahi-browse timed out after %.1fs "
                "while resolving %s"
            )
            % (duration, service_type)
        )
        return []
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
    service_types = _service_types(cluster, environment)

    resolved_lines: List[str] = []
    for service_type in service_types:
        lines = list(
            _browse_service_type(
                service_type,
                runner,
                resolve=True,
                timeout=_DEFAULT_BROWSE_TIMEOUT,
            )
        )
        if not lines:
            continue
        resolved_lines.extend(lines)

    if resolved_lines:
        records = parse_mdns_records(resolved_lines, cluster, environment)
        if records:
            return records

    fallback_lines: List[str] = []
    for service_type in service_types:
        lines = list(
            _browse_service_type(
                service_type,
                runner,
                resolve=False,
                timeout=_DEFAULT_BROWSE_TIMEOUT,
            )
        )
        if not lines:
            continue
        fallback_lines.extend(lines)
        # Match previous behaviour by returning as soon as unresolved records are
        # observed for any service type. This preserves call expectations in the
        # tests and avoids unnecessary avahi-browse invocations.
        break

    if fallback_lines:
        records = parse_mdns_records(fallback_lines, cluster, environment)
        if records:
            return records

    return []


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

    expected_norm = normalize_hostname(expected_host)
    if not expected_norm:
        return None

    attempts = max(retries, 1)
    delay = max(delay, 0.0)

    expect_addr = (expect_addr or "").strip() or None

    fallback_candidate: Optional[str] = None
    fallback_addr: Optional[str] = None
    host_only_candidate: Optional[str] = None
    host_only_value: Optional[str] = None

    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    for attempt in range(1, attempts + 1):
        records = _collect_mdns_records(cluster, env, runner)
        if not records:
            _log(
                "[k3s-discover mdns] Attempt %d/%d: no mDNS records discovered for cluster=%s env=%s"
                % (attempt, attempts, cluster, env)
            )
            if attempt < attempts and delay > 0:
                _log(
                    "[k3s-discover mdns] Attempt %d/%d: retrying in %.1fs"
                    % (attempt, attempts, delay)
                )
                sleep(delay)
            continue

        _log(
            "[k3s-discover mdns] Attempt %d/%d: collected %d record(s) for cluster=%s env=%s"
            % (attempt, attempts, len(records), cluster, env)
        )

        host_match_found = False
        diag_messages: List[str] = []
        observed_hosts: List[str] = []

        for record in records:
            observed_hosts.append(record.host)
            txt = record.txt

            phase = txt.get("phase")
            role = txt.get("role")
            leader_raw = txt.get("leader", "")

            record_norm = norm_host(record.host)
            leader_norm = norm_host(leader_raw)
            if require_phase is not None:
                phase_matches = phase == require_phase
                role_matches = role == require_phase if role else False
                if not phase_matches and not role_matches:
                    diag_messages.append(
                        (
                            "[k3s-discover mdns] Attempt %d/%d: skipped %s because "
                            "require_phase=%s (phase=%s role=%s)"
                        )
                        % (
                            attempt,
                            attempts,
                            record.host or "<none>",
                            require_phase,
                            phase or "<missing>",
                            role or "<missing>",
                        )
                    )
                    continue

            host_match = record_norm == expected_norm if record_norm else False
            leader_match = leader_norm == expected_norm if leader_norm else False
            if not (host_match or leader_match):
                diag_messages.append(
                    (
                        "[k3s-discover mdns] Attempt %d/%d: host mismatch for %s (raw=%s norm=%s) "
                        "leader=%s (norm=%s) expected raw=%s norm=%s"
                    )
                    % (
                        attempt,
                        attempts,
                        record.host or "<none>",
                        record.host or "<none>",
                        record_norm or "<empty>",
                        leader_raw or "<none>",
                        leader_norm or "<empty>",
                        expected_host,
                        expected_norm,
                    )
                )
                continue

            host_match_found = True

            if expect_addr:
                record_addr = record.address.strip()
                txt_addr = txt.get("a", "").strip()
                txt_addr_alt = txt.get("addr", "").strip()
                observed_addrs = [
                    addr for addr in (record_addr, txt_addr, txt_addr_alt) if addr
                ]
                if expect_addr in observed_addrs:
                    return record.host

                categories = _categorise_addresses(observed_addrs)

                if fallback_candidate is None and "ipv6" in categories and "ipv4" not in categories:
                    fallback_candidate = record.host
                    for candidate, category in zip(observed_addrs, categories):
                        if category == "ipv6":
                            fallback_addr = candidate
                            break
                if host_only_candidate is None and (
                    not observed_addrs
                    or (
                        "other" in categories
                        and "ipv4" not in categories
                        and "ipv6" not in categories
                    )
                ):
                    host_only_candidate = record.host
                    host_only_value = observed_addrs[0] if observed_addrs else None

                observed_text = ", ".join(observed_addrs) if observed_addrs else "<none>"
                reason = _describe_addr_mismatch(expect_addr, observed_addrs, categories)
                diag_messages.append(
                    (
                        "[k3s-discover mdns] Attempt %d/%d: observed host %s (phase=%s role=%s) "
                        "with addresses %s; expected %s. %s"
                        % (
                            attempt,
                            attempts,
                            record.host,
                            phase or "<unknown>",
                            role or "<unknown>",
                            observed_text,
                            expect_addr,
                            reason,
                        )
                    )
                )
                continue

            return record.host

        for message in diag_messages:
            _log(message)

        if not host_match_found:
            unique_hosts = sorted({
                norm_host(host) for host in observed_hosts if host
            })
            observed_text = ", ".join(unique_hosts) if unique_hosts else "<none>"
            _log(
                "[k3s-discover mdns] Attempt %d/%d: observed hosts %s but none matched expected %s"
                % (attempt, attempts, observed_text, expected_norm)
            )

        if attempt < attempts and delay > 0:
            _log(
                "[k3s-discover mdns] Attempt %d/%d did not confirm advertisement; retrying in %.1fs"
                % (attempt, attempts, delay)
            )
            sleep(delay)

    if fallback_candidate and expect_addr:
        mismatch = fallback_addr or "<unknown>"
        _log(
            (
                "[k3s-discover mdns] WARN: expected IPv4 %s for %s but "
                "observed %s; assuming match after %d attempts"
            )
            % (expect_addr, expected_norm, mismatch, attempts)
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
        _log(message)
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
        _LOGGER.out(observed)
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())


__all__ = [
    "build_publish_cmd",
    "_norm_host",
    "_same_host",
    "ensure_self_ad_is_visible",
    "norm_host",
    "normalize_hostname",
    "build_publish_command",
]
