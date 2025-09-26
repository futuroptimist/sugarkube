#!/usr/bin/env python3
"""Generate structured metadata for a pi-gen build.

The output captures reproducibility inputs like the upstream pi-gen commit,
stage durations, and sugarkube build configuration so downstream tooling can
produce provenance manifests and release notes without re-parsing logs.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import pathlib
import platform
import re
import sys
from typing import Dict, Iterable, List, Tuple

_STAGE_RE = re.compile(r"^\[(\d+):(\d+):(\d+)\]\s+(Begin|End)\s+([^/]+)$")


@dataclasses.dataclass(frozen=True)
class StageSpan:
    name: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class StageTimer:
    """Parse pi-gen's build.log to derive per-stage timings."""

    def __init__(self) -> None:
        self._starts: Dict[str, float] = {}
        self._durations: Dict[str, float] = {}
        self._spans: List[StageSpan] = []
        self._last_timestamp: float = 0.0
        self._first_timestamp: float | None = None
        self._day_offset: float = 0.0

    def observe(self, line: str) -> None:
        match = _STAGE_RE.match(line.strip())
        if not match:
            return
        hour, minute, second = (int(match.group(i)) for i in range(1, 4))
        seconds = hour * 3600 + minute * 60 + second
        if seconds + self._day_offset < self._last_timestamp:
            # pi-gen logs do not include a date so long builds can wrap at midnight.
            self._day_offset += 24 * 3600
        timestamp = seconds + self._day_offset
        self._last_timestamp = timestamp
        if self._first_timestamp is None:
            self._first_timestamp = timestamp
        phase = match.group(4)
        name = match.group(5)
        if phase == "Begin":
            self._starts[name] = timestamp
        elif phase == "End" and name in self._starts:
            start = self._starts.pop(name)
            span = StageSpan(name=name, start=start, end=timestamp)
            self._spans.append(span)
            self._durations[name] = self._durations.get(name, 0.0) + span.duration

    def durations(self) -> Dict[str, float]:
        return {k: v for k, v in sorted(self._durations.items())}

    def spans(self) -> List[StageSpan]:
        return sorted(self._spans, key=lambda span: span.start)

    def incomplete(self) -> Dict[str, float]:
        return {k: v for k, v in sorted(self._starts.items(), key=lambda item: item[1])}

    def first_timestamp(self) -> float | None:
        return self._first_timestamp

    def elapsed(self) -> float:
        if self._first_timestamp is None:
            return 0.0
        return max(self._last_timestamp - self._first_timestamp, 0.0)


def _parse_stage_log(path: pathlib.Path) -> StageTimer:
    timer = StageTimer()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                timer.observe(line)
    except FileNotFoundError:
        return timer
    return timer


def _load_stage_durations(path: pathlib.Path) -> Dict[str, float]:
    return _parse_stage_log(path).durations()


def _parse_options(pairs: Iterable[str]) -> Dict[str, object]:
    options: Dict[str, object] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"option '{item}' is missing '='")
        key, raw_value = item.split("=", 1)
        value: object
        lowered = raw_value.lower()
        if lowered in {"true", "false"}:
            value = lowered == "true"
        else:
            try:
                value = int(raw_value)
            except ValueError:
                try:
                    value = float(raw_value)
                except ValueError:
                    value = raw_value
        options[key] = value
    return options


def _compute_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_checksum(path: pathlib.Path, image_path: pathlib.Path | None) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        if image_path is not None:
            return _compute_sha256(image_path)
        raise ValueError(f"checksum file '{path}' is empty")
    first_line = text.splitlines()[0]
    digest = first_line.split()[0]
    if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        if image_path is not None:
            return _compute_sha256(image_path)
        raise ValueError(f"checksum '{digest}' from '{path}' is not a SHA-256 hash")
    return digest


def _load_verifier(verifier_path: str | None) -> Dict[str, object]:
    if not verifier_path:
        return {"status": "not_run"}
    path = pathlib.Path(verifier_path)
    if not path.exists():
        return {"status": "not_found", "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid", "error": str(exc), "path": str(path)}
    return {"status": "ok", "data": data, "path": str(path)}


def _default_runner() -> Tuple[str, str]:
    if hasattr(os, "uname"):
        info = os.uname()
        return info.sysname, info.machine
    return platform.system() or "unknown", platform.machine() or "unknown"


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Destination metadata JSON path")
    parser.add_argument("--image", required=True, help="Built image path")
    parser.add_argument(
        "--checksum",
        required=True,
        help="SHA-256 file produced alongside the image",
    )
    parser.add_argument(
        "--build-log",
        required=False,
        help="pi-gen work/<img>/build.log path",
    )
    parser.add_argument("--pi-gen-branch", required=True)
    parser.add_argument("--pi-gen-url", required=True)
    parser.add_argument("--pi-gen-commit", required=True)
    parser.add_argument(
        "--pi-gen-stages",
        required=True,
        help="Whitespace-separated stage list",
    )
    parser.add_argument("--repo-commit", required=True)
    parser.add_argument("--repo-ref", required=False)
    parser.add_argument("--build-start", required=True)
    parser.add_argument("--build-end", required=True)
    parser.add_argument("--duration-seconds", required=True, type=float)
    parser.add_argument("--runner-os", required=False)
    parser.add_argument("--runner-arch", required=False)
    parser.add_argument(
        "--option",
        action="append",
        default=[],
        help="Additional key=value pairs to embed",
    )
    parser.add_argument(
        "--verifier-json",
        required=False,
        help="Path to cached verifier JSON output",
    )
    parser.add_argument(
        "--stage-summary",
        required=False,
        help="Destination for structured stage summary JSON",
    )
    return parser.parse_args(argv)


def _write_stage_summary(
    output_path: pathlib.Path,
    timer: StageTimer,
    log_path: pathlib.Path | None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    spans = timer.spans()
    base = timer.first_timestamp() or 0.0
    stage_entries = [
        {
            "name": span.name,
            "start_offset_seconds": int(round(span.start - base)),
            "end_offset_seconds": int(round(span.end - base)),
            "duration_seconds": int(round(span.duration)),
        }
        for span in spans
    ]
    incomplete_entries = [
        {
            "name": name,
            "start_offset_seconds": int(round(start - base)),
        }
        for name, start in timer.incomplete().items()
    ]

    summary = {
        "log_path": str(log_path) if log_path else None,
        "stage_count": len(stage_entries),
        "total_duration_seconds": int(
            round(sum(entry["duration_seconds"] for entry in stage_entries))
        ),
        "observed_elapsed_seconds": int(round(timer.elapsed())),
        "stages": stage_entries,
        "incomplete_stages": incomplete_entries,
        "generated_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: List[str]) -> int:
    args = _parse_args(argv)

    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image_path = pathlib.Path(args.image)
    checksum_path = pathlib.Path(args.checksum)
    build_log_path = pathlib.Path(args.build_log) if args.build_log else None

    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")
    if not checksum_path.exists():
        raise FileNotFoundError(f"checksum file not found: {checksum_path}")

    checksum = _read_checksum(checksum_path, image_path)
    image_size = image_path.stat().st_size

    stage_timer = StageTimer()
    stage_durations: Dict[str, float] = {}
    if build_log_path:
        stage_timer = _parse_stage_log(build_log_path)
        stage_durations = stage_timer.durations()

    options = _parse_options(args.option)

    runner_os, runner_arch = _default_runner()

    metadata = {
        "image": {
            "path": str(image_path),
            "sha256": checksum,
            "size_bytes": image_size,
        },
        "checksum_path": str(checksum_path),
        "build_log_path": str(build_log_path) if build_log_path else None,
        "build": {
            "start": args.build_start,
            "end": args.build_end,
            "duration_seconds": args.duration_seconds,
            "stage_durations": stage_durations,
            "pi_gen": {
                "url": args.pi_gen_url,
                "branch": args.pi_gen_branch,
                "commit": args.pi_gen_commit,
                "stages": args.pi_gen_stages.split(),
            },
            "runner": {
                "os": args.runner_os or runner_os,
                "arch": args.runner_arch or runner_arch,
            },
        },
        "repository": {
            "commit": args.repo_commit,
            "ref": args.repo_ref,
        },
        "options": options,
        "verifier": _load_verifier(args.verifier_json),
        "generated_at": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }

    output_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.stage_summary:
        summary_path = pathlib.Path(args.stage_summary)
        _write_stage_summary(summary_path, stage_timer, build_log_path)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via unit tests
    sys.exit(main(sys.argv[1:]))
