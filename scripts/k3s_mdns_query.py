"""Helpers for querying k3s mDNS advertisements via Avahi."""

from __future__ import annotations

import errno
import os
import subprocess
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from k3s_mdns_parser import MdnsRecord, parse_mdns_records
from mdns_helpers import _norm_host

DebugFn = Optional[Callable[[str], None]]

_DUMP_PATH = Path("/tmp/sugarkube-mdns.txt")
_TIMEOUT_ENV = "SUGARKUBE_MDNS_QUERY_TIMEOUT"
_DEFAULT_TIMEOUT = 10.0


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
        "--terminate",
    ]
    if resolve:
        command.append("--resolve")
    if mode in {"server-first", "server-count", "server-select"}:
        command.append("--ignore-local")
    command.append(service_type)
    return command


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
    try:
        result = runner(command, **run_kwargs)
    except subprocess.TimeoutExpired as exc:
        if debug is not None and timeout is not None:
            debug("avahi-browse timed out after " f"{timeout:g}s; continuing without mDNS results")
        stdout = exc.stdout or exc.output or ""
        stderr = exc.stderr or ""
        return subprocess.CompletedProcess(
            command,
            returncode=124,
            stdout=stdout,
            stderr=stderr,
        )
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
    if result.returncode != 0 and debug is not None:
        debug(f"avahi-browse exited with {result.returncode}; continuing with available data")
        if result.stderr:
            debug(result.stderr.strip())
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
        result = _invoke_avahi(
            mode,
            service_type,
            runner,
            debug,
            timeout,
            resolve=resolve,
        )
        new_lines = _normalize_record_lines(result.stdout.splitlines())
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
        if not records:
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

    if debug is not None and not records and lines and not fixture_path:
        try:
            _DUMP_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            debug(f"Wrote browse dump to {_DUMP_PATH}")
        except OSError:
            debug("Unable to write browse dump to /tmp")

    return _render_mode(mode, records)


__all__ = ["query_mdns"]
