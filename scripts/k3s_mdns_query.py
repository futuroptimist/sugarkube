"""Helpers for querying k3s mDNS advertisements via Avahi."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from k3s_mdns_parser import MdnsRecord, parse_mdns_records

DebugFn = Optional[Callable[[str], None]]

_DUMP_PATH = Path("/tmp/sugarkube-mdns.txt")


def _build_command(mode: str) -> List[str]:
    command = [
        "avahi-browse",
        "--parsable",
        "--terminate",
        "--resolve",
    ]
    if mode in {"server-first", "server-count"}:
        command.append("--ignore-local")
    command.append("_https._tcp")
    return command


def _invoke_avahi(
    mode: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    debug: DebugFn,
) -> subprocess.CompletedProcess[str]:
    command = _build_command(mode)
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        if debug is not None:
            debug(
                "avahi-browse executable not found; continuing without mDNS results"
            )
        return subprocess.CompletedProcess(
            command,
            returncode=127,
            stdout="",
            stderr="",
        )
    if result.returncode != 0 and debug is not None:
        debug(
            f"avahi-browse exited with {result.returncode}; continuing with available data"
        )
        if result.stderr:
            debug(result.stderr.strip())
    return result


def _load_lines_from_fixture(fixture_path: str) -> Iterable[str]:
    try:
        text = Path(fixture_path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [line for line in text.splitlines() if line]


def _load_lines_from_avahi(
    mode: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    debug: DebugFn,
) -> Iterable[str]:
    result = _invoke_avahi(mode, runner, debug)
    lines = [line for line in result.stdout.splitlines() if line]
    if debug is not None and not lines and result.stdout:
        try:
            _DUMP_PATH.write_text(result.stdout, encoding="utf-8")
            debug(f"Wrote browse dump to {_DUMP_PATH}")
        except OSError:
            debug("Unable to write browse dump to /tmp")
    return lines


def _render_mode(mode: str, records: Iterable[MdnsRecord]) -> List[str]:
    if mode == "server-first":
        for record in records:
            if record.txt.get("role") == "server":
                return [record.host]
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
            if record.host in seen:
                continue
            seen.add(record.host)
            outputs.append(record.host)
        return outputs

    if mode == "server-hosts":
        seen = set()
        outputs: List[str] = []
        for record in records:
            if record.txt.get("role") != "server":
                continue
            if record.host in seen:
                continue
            seen.add(record.host)
            outputs.append(record.host)
        return outputs

    if mode == "bootstrap-leaders":
        seen = set()
        outputs: List[str] = []
        for record in records:
            if record.txt.get("role") != "bootstrap":
                continue
            leader = record.txt.get("leader", record.host)
            if leader in seen:
                continue
            seen.add(leader)
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

    if fixture_path:
        lines = _load_lines_from_fixture(fixture_path)
    else:
        lines = _load_lines_from_avahi(mode, runner, debug)

    records = parse_mdns_records(lines, cluster, environment)

    if debug is not None and not records and lines and not fixture_path:
        try:
            _DUMP_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
            debug(f"Wrote browse dump to {_DUMP_PATH}")
        except OSError:
            debug("Unable to write browse dump to /tmp")

    return _render_mode(mode, records)


__all__ = ["query_mdns"]
