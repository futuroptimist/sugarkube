"""
Helpers for querying k3s mDNS advertisements via Avahi.

This module provides functions to discover k3s nodes on the local network using
multicast DNS (mDNS) service browsing. It wraps avahi-browse and handles various
edge cases and error conditions.

Key Behaviors (as of 2025-11-15 fixes):

1. **Network Discovery by Default**: By default, avahi-browse waits for actual
   mDNS multicast responses on the network. This is essential for initial cluster
   formation when nodes have never seen each other before.
   
   - Set SUGARKUBE_MDNS_NO_TERMINATE=0 to use --terminate flag (cache-only, fast)
   - Default is SUGARKUBE_MDNS_NO_TERMINATE=1 (network discovery, reliable)

2. **No --ignore-local Flag**: Nodes can discover any k3s service on the network,
   including their own (for self-verification). This allows bootstrap nodes to
   confirm their service publications.

3. **Robust Error Handling**: Handles TimeoutExpired exceptions gracefully,
   converting bytes to str as needed to prevent TypeErrors during diagnostics.

Environment Variables:
    SUGARKUBE_MDNS_NO_TERMINATE: Controls --terminate flag (default: "1", no terminate)
    SUGARKUBE_MDNS_QUERY_TIMEOUT: Query timeout in seconds (default: 10.0)
    ALLOW_IFACE: Pin avahi-browse to specific interface (e.g., "eth0")
    SUGARKUBE_DEBUG: Enable detailed debug logging
    SUGARKUBE_MDNS_FIXTURE_FILE: Use fixture file instead of live avahi-browse

See Also:
    - outages/2025-11-15-mdns-terminate-flag-prevented-discovery.json
    - outages/2025-11-15-mdns-ignore-local-blocked-verification.json
    - outages/2025-11-15-mdns-timeout-bytes-str-mismatch.json
"""

from __future__ import annotations

import errno
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from k3s_mdns_parser import MdnsRecord, parse_mdns_records
from mdns_helpers import _norm_host

DebugFn = Optional[Callable[[str], None]]

_DUMP_PATH = Path("/tmp/sugarkube-mdns.txt")
_TIMEOUT_ENV = "SUGARKUBE_MDNS_QUERY_TIMEOUT"
_DEFAULT_TIMEOUT = 10.0
_RETRY_DELAY = 1.5  # Delay between retry attempts in seconds
_NO_TERMINATE_ENV = "SUGARKUBE_MDNS_NO_TERMINATE"  # Skip --terminate to wait for network responses


def _resolve_timeout(value: Optional[str]) -> Optional[float]:
    if not value:
        return _DEFAULT_TIMEOUT
    try:
        parsed = float(value)
    except ValueError:
        return _DEFAULT_TIMEOUT
    if parsed <= 0:
        return None
    return parsed


def _service_type(cluster: str, environment: str) -> str:
    return f"_k3s-{cluster}-{environment}._tcp"


def _service_types(cluster: str, environment: str) -> List[str]:
    types = [_service_type(cluster, environment)]
    legacy = "_https._tcp"
    if legacy not in types:
        types.append(legacy)
    return types


def _build_command(mode: str, service_type: str, *, resolve: bool = True) -> List[str]:
    command = [
        "avahi-browse",
        "--parsable",
    ]
    
    # --terminate causes avahi-browse to dump only cached entries and exit immediately.
    # This is fast but won't discover services that haven't been cached yet.
    # For initial cluster formation, we want to wait for network responses,
    # so we skip --terminate by default. Set SUGARKUBE_MDNS_NO_TERMINATE=0 to re-enable it.
    use_terminate = os.environ.get(_NO_TERMINATE_ENV, "1").strip() == "0"
    if use_terminate:
        command.append("--terminate")
    
    if resolve:
        command.append("--resolve")
    # Note: --ignore-local prevents discovering services published by THIS host's Avahi daemon.
    # For cross-node discovery, we don't need this flag - we want to see all k3s services on the network.
    # Removing this flag allows nodes to discover any k3s server, including for self-checks.
    # if mode in {"server-first", "server-count", "server-select"}:
    #     command.append("--ignore-local")

    # Add interface pinning if ALLOW_IFACE is set
    allow_iface = os.environ.get("ALLOW_IFACE", "").strip()
    if allow_iface:
        command.append(f"--interface={allow_iface}")

    command.append(service_type)
    return command


def _dump_avahi_journal(debug: DebugFn) -> None:
    """Dump tail of avahi-daemon journal logs for diagnostics."""
    if debug is None:
        return

    try:
        result = subprocess.run(
            ["journalctl", "-u", "avahi-daemon", "-n", "200", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            # Sanitize log output (remove any potential sensitive data)
            log_lines = result.stdout.splitlines()
            sanitized_lines = []
            for line in log_lines:
                # Basic sanitization: remove IP addresses in private ranges if needed
                # For now, we'll include the logs as-is since they're system logs
                sanitized_lines.append(line)

            debug("=== Avahi daemon journal (last 200 lines) ===")
            for line in sanitized_lines[-200:]:
                debug(line)
            debug("=== End of Avahi daemon journal ===")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        debug(f"Unable to fetch avahi-daemon journal: {e}")


def _try_dbus_browser(
    service_type: str, debug: DebugFn, timeout: Optional[float]
) -> Tuple[int, str, str]:
    """
    Try to browse mDNS services using D-Bus via gdbus or busctl.
    Returns (returncode, stdout, stderr).
    """
    # Try gdbus first
    if os.path.isfile("/usr/bin/gdbus") or os.path.isfile("/bin/gdbus"):
        try:
            # Use gdbus to call Avahi's ServiceBrowser
            cmd = [
                "gdbus",
                "call",
                "--system",
                "--dest", "org.freedesktop.Avahi",
                "--object-path", "/org/freedesktop/Avahi/Server",
                "--method", "org.freedesktop.Avahi.Server.ServiceBrowserNew",
                "-1",  # IF_UNSPEC
                "-1",  # PROTO_UNSPEC
                service_type,
                "local",
                "0",  # flags
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout else 10,
                check=False,
            )
            if result.returncode == 0:
                if debug:
                    debug(f"D-Bus browse via gdbus succeeded (exit {result.returncode})")
                return (result.returncode, result.stdout, result.stderr)
            else:
                if debug:
                    debug(
                        f"D-Bus browse via gdbus failed "
                        f"(exit {result.returncode}): {result.stderr}"
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            if debug:
                debug(f"gdbus not available or failed: {e}")

    # Try busctl as fallback
    if os.path.isfile("/usr/bin/busctl") or os.path.isfile("/bin/busctl"):
        try:
            cmd = [
                "busctl",
                "call",
                "--system",
                "org.freedesktop.Avahi",
                "/org/freedesktop/Avahi/Server",
                "org.freedesktop.Avahi.Server",
                "ServiceBrowserNew",
                "iissu",
                "-1",  # interface
                "-1",  # protocol
                service_type,
                "local",
                "0",  # flags
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout else 10,
                check=False,
            )
            if result.returncode == 0:
                if debug:
                    debug(f"D-Bus browse via busctl succeeded (exit {result.returncode})")
                return (result.returncode, result.stdout, result.stderr)
            else:
                if debug:
                    debug(
                        f"D-Bus browse via busctl failed "
                        f"(exit {result.returncode}): {result.stderr}"
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            if debug:
                debug(f"busctl not available or failed: {e}")

    return (1, "", "D-Bus browser not available")


def _invoke_avahi(
    mode: str,
    service_type: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    debug: DebugFn,
    timeout: Optional[float],
    *,
    resolve: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = _build_command(mode, service_type, resolve=resolve)
    
    if debug is not None:
        debug(f"_invoke_avahi: command={' '.join(command)}")
        debug(f"_invoke_avahi: timeout={timeout}s")
    
    run_kwargs = {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    # Python 3.14+ changed subprocess behavior: when calling subprocess.run without
    # an explicit env parameter, it may not inherit all environment variables correctly,
    # particularly PATH modifications from test fixtures. We now ALWAYS pass env explicitly.
    # For test mocks that don't accept env parameter, we rely on them not being subprocess.run.
    if runner is subprocess.run:
        # Build env dict explicitly to work around Python 3.14 subprocess.run issues
        run_kwargs["env"] = dict(os.environ)
    if timeout is not None:
        run_kwargs["timeout"] = timeout

    # Try avahi-browse with retry logic
    result: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in range(1, 3):  # Try twice: initial attempt + 1 retry
        try:
            result = runner(command, **run_kwargs)

            # Log exact exit code and stderr
            if debug is not None:
                debug(f"avahi-browse attempt {attempt}: exit_code={result.returncode}")
                if result.stderr:
                    debug(f"avahi-browse stderr: {result.stderr.strip()}")
                if result.stdout:
                    lines_count = len(result.stdout.splitlines())
                    debug(f"avahi-browse stdout: {lines_count} lines")
                    # Log first few lines of output for debugging
                    for i, line in enumerate(result.stdout.splitlines()[:10]):
                        debug(f"avahi-browse stdout[{i}]: {line}")

            # If successful or has output, break
            if result.returncode == 0 or result.stdout:
                break

            # If first attempt failed with non-zero exit and no output, retry
            if attempt == 1:
                if debug is not None:
                    debug(
                        f"avahi-browse attempt {attempt} failed with exit "
                        f"{result.returncode}, retrying after {_RETRY_DELAY}s..."
                    )
                time.sleep(_RETRY_DELAY)

        except subprocess.TimeoutExpired as exc:
            if debug is not None and timeout is not None:
                debug(f"avahi-browse attempt {attempt} timed out after {timeout:g}s")
            # TimeoutExpired may contain bytes even when text=True is used
            stdout = exc.stdout or exc.output or ""
            stderr = exc.stderr or ""
            # Convert bytes to str if necessary
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            result = subprocess.CompletedProcess(
                command,
                returncode=124,
                stdout=stdout,
                stderr=stderr,
            )
            
            # Log captured output from timeout for debugging
            if debug is not None:
                if stderr:
                    debug(f"avahi-browse stderr (from timeout): {stderr.strip()}")
                if stdout:
                    lines_count = len(stdout.splitlines())
                    debug(f"avahi-browse stdout (from timeout): {lines_count} lines")
                    # Log first few lines of output for debugging
                    for i, line in enumerate(stdout.splitlines()[:10]):
                        debug(f"avahi-browse stdout[{i}]: {line}")
            
            if attempt == 1:
                if debug is not None:
                    debug(f"Retrying after timeout (attempt {attempt})...")
                time.sleep(_RETRY_DELAY)
            else:
                break

        except FileNotFoundError:
            if debug is not None:
                debug("avahi-browse executable not found; continuing without mDNS results")
            return subprocess.CompletedProcess(
                command,
                returncode=127,
                stdout="",
                stderr="",
            )
        except OSError as exc:
            if exc.errno == errno.ENOEXEC:
                fallback = ["bash", *command]
                if debug is not None:
                    debug("avahi-browse returned ENOEXEC; retrying with Bash fallback")
                result = runner(fallback, **run_kwargs)
            else:
                raise

    # If all avahi-browse attempts failed, try D-Bus browser as fallback
    if result is not None and result.returncode != 0 and not result.stdout:
        if debug is not None:
            debug(
                f"avahi-browse failed after retries (exit {result.returncode}), "
                "trying D-Bus browser..."
            )

        dbus_exit, dbus_stdout, dbus_stderr = _try_dbus_browser(service_type, debug, timeout)

        if dbus_exit == 0:
            # D-Bus browser succeeded, but we can't parse its output directly
            # Just log that it worked
            if debug is not None:
                debug(
                    "D-Bus ServiceBrowser call succeeded; however, "
                    "avahi-browse is still needed for record parsing"
                )

        # Dump avahi-daemon journal for diagnostics on failure
        if debug is not None:
            debug("Browse failed; dumping avahi-daemon journal for diagnostics...")
            _dump_avahi_journal(debug)

    if result is None:
        # Fallback in case something unexpected happened
        result = subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout="",
            stderr="Unexpected error in _invoke_avahi",
        )

    return result


def _load_lines_from_fixture(fixture_path: str) -> Iterable[str]:
    try:
        text = Path(fixture_path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line for line in text.splitlines() if line]


def _normalize_record_lines(lines: Iterable[str]) -> List[str]:
    """Collapse Avahi output so each record occupies a single line."""

    collapsed: List[str] = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line[0] in {"=", "+", "@"} or not collapsed:
            collapsed.append(line)
            continue

        collapsed[-1] += line

    return collapsed


def _load_lines_from_avahi(
    mode: str,
    cluster: str,
    environment: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    debug: DebugFn,
    timeout: Optional[float],
    *,
    resolve: bool = True,
) -> Iterable[str]:
    lines: List[str] = []
    for service_type in _service_types(cluster, environment):
        if debug is not None:
            debug(f"_load_lines_from_avahi: browsing service_type={service_type}, resolve={resolve}")
        result = _invoke_avahi(
            mode,
            service_type,
            runner,
            debug,
            timeout,
            resolve=resolve,
        )
        new_lines = _normalize_record_lines(result.stdout.splitlines())
        if debug is not None:
            debug(f"_load_lines_from_avahi: got {len(new_lines)} normalized lines from {service_type}")
        if debug is not None and not new_lines and result.stdout:
            try:
                _DUMP_PATH.write_text(result.stdout, encoding="utf-8")
                debug(f"Wrote browse dump to {_DUMP_PATH}")
            except OSError:
                debug("Unable to write browse dump to /tmp")
        lines.extend(new_lines)
    return lines


def _render_mode(mode: str, records: Iterable[MdnsRecord]) -> List[str]:
    if mode == "server-first":
        for record in records:
            if record.txt.get("role") == "server":
                return [record.host]
        return []

    if mode == "server-select":
        for record in records:
            if record.txt.get("role") != "server":
                continue
            phase = record.txt.get("phase") or record.txt.get("state") or ""
            fields = []
            if phase:
                fields.append(f"mode={phase}")
            else:
                fields.append("mode=")
            fields.append(f"host={record.host}")
            fields.append(f"port={record.port}")
            if record.address:
                fields.append(f"address={record.address}")
            txt_ip4 = record.txt.get("ip4")
            txt_ip6 = record.txt.get("ip6")
            txt_host = record.txt.get("host")
            if txt_ip4:
                fields.append(f"txt_ip4={txt_ip4}")
            if txt_ip6:
                fields.append(f"txt_ip6={txt_ip6}")
            if txt_host:
                fields.append(f"txt_host={txt_host}")
            return [" ".join(fields)]
        return []

    if mode == "server-count":
        count = sum(1 for record in records if record.txt.get("role") == "server")
        return [str(count)]

    if mode == "bootstrap-hosts":
        seen = set()
        outputs: List[str] = []
        for record in records:
            if record.txt.get("role") != "bootstrap":
                continue
            host_key = _norm_host(record.host)
            if host_key in seen:
                continue
            seen.add(host_key)
            outputs.append(record.host)
        return outputs

    if mode == "server-hosts":
        seen = set()
        outputs: List[str] = []
        for record in records:
            if record.txt.get("role") != "server":
                continue
            host_key = _norm_host(record.host)
            if host_key in seen:
                continue
            seen.add(host_key)
            outputs.append(record.host)
        return outputs

    if mode == "bootstrap-leaders":
        seen = set()
        outputs: List[str] = []
        for record in records:
            if record.txt.get("role") != "bootstrap":
                continue
            leader = record.txt.get("leader", record.host)
            leader_key = _norm_host(leader)
            if leader_key in seen:
                continue
            seen.add(leader_key)
            outputs.append(leader)
        return outputs

    raise ValueError(f"Unsupported mode: {mode}")


def query_mdns(
    mode: str,
    cluster: str,
    environment: str,
    *,
    fixture_path: Optional[str] = None,
    debug: DebugFn = None,
    runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
) -> List[str]:
    """Run an mDNS browse for sugarkube k3s advertisements."""

    if runner is None:
        runner = subprocess.run  # type: ignore[assignment]

    timeout = _resolve_timeout(os.environ.get(_TIMEOUT_ENV))
    
    if debug is not None:
        service_types = _service_types(cluster, environment)
        debug(f"query_mdns: mode={mode}, cluster={cluster}, env={environment}")
        debug(f"query_mdns: service_types={service_types}")
        debug(f"query_mdns: timeout={timeout}s")
        debug(f"query_mdns: no_terminate={os.environ.get(_NO_TERMINATE_ENV, '0')}")

    if fixture_path:
        lines = _load_lines_from_fixture(fixture_path)
        records = parse_mdns_records(lines, cluster, environment)
    else:
        lines = _load_lines_from_avahi(
            mode,
            cluster,
            environment,
            runner,
            debug,
            timeout,
        )
        records = parse_mdns_records(lines, cluster, environment)
        
        if debug is not None:
            debug(f"query_mdns: initial browse returned {len(lines)} lines, {len(records)} records")
        
        if not records:
            if debug is not None:
                debug("query_mdns: no records found, trying without --resolve")
            fallback_lines = _load_lines_from_avahi(
                mode,
                cluster,
                environment,
                runner,
                debug,
                timeout,
                resolve=False,
            )
            if fallback_lines:
                lines = fallback_lines
                records = parse_mdns_records(lines, cluster, environment)
                if debug is not None:
                    debug(f"query_mdns: fallback browse returned {len(lines)} lines, {len(records)} records")

    if debug is not None and not records and lines and not fixture_path:
        try:
            # Ensure all lines are strings (handle potential bytes from error paths)
            str_lines = []
            for line in lines:
                if isinstance(line, bytes):
                    str_lines.append(line.decode("utf-8", errors="replace"))
                else:
                    str_lines.append(str(line))
            _DUMP_PATH.write_text("\n".join(str_lines) + "\n", encoding="utf-8")
            debug(f"Wrote browse dump to {_DUMP_PATH}")
        except (OSError, TypeError) as e:
            debug(f"Unable to write browse dump to /tmp: {e}")
    
    result = _render_mode(mode, records)
    if debug is not None:
        debug(f"query_mdns: returning {len(result)} results for mode={mode}")
        if result:
            for r in result[:5]:  # Log first 5 results
                debug(f"query_mdns: result: {r}")

    return result


__all__ = ["query_mdns"]
