"""Helpers for capturing and parsing OpenSCAD echo output."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "EchoLine",
    "OpenScadRunResult",
    "parse_echo_line",
    "run_openscad_and_capture_echoes",
]


@dataclass
class EchoLine:
    label: str
    values: dict[str, Any]
    raw: str


@dataclass
class OpenScadRunResult:
    stdout: str
    stderr: str
    echo_lines: list[EchoLine]

    def last_for_label(self, label: str) -> EchoLine:
        for echo_line in reversed(self.echo_lines):
            if echo_line.label == label:
                return echo_line
        raise KeyError(f"echo label '{label}' not found")


def _split_top_level_fields(payload: str) -> list[str]:
    fields: list[str] = []
    buf: list[str] = []
    depth = 0
    in_string = False
    escaped = False

    for char in payload:
        if escaped:
            buf.append(char)
            escaped = False
            continue

        if char == "\\" and in_string:
            buf.append(char)
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            buf.append(char)
            continue

        if not in_string:
            if char in "[{(":
                depth += 1
            elif char in "]})":
                depth -= 1

            if char == "," and depth == 0:
                fields.append("".join(buf).strip())
                buf = []
                continue

        buf.append(char)

    if buf:
        fields.append("".join(buf).strip())
    return fields


def _normalize_scalars(raw_value: str) -> str:
    return (
        raw_value.replace("true", "True")
        .replace("false", "False")
        .replace("undef", "None")
    )


def _parse_value(raw_value: str) -> Any:
    value = raw_value.strip()
    normalized = _normalize_scalars(value)

    if normalized.startswith("[") or normalized.startswith("{"):
        try:
            return ast.literal_eval(normalized)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"failed to parse array value: {raw_value}") from exc

    if normalized.startswith('"') and normalized.endswith('"'):
        return normalized.strip('"')

    if normalized in {"True", "False"}:
        return normalized == "True"
    if normalized == "None":
        return None

    try:
        return int(normalized)
    except ValueError:
        try:
            return float(normalized)
        except ValueError:
            raise ValueError(f"unrecognised value: {raw_value}") from None


def parse_echo_line(line: str) -> EchoLine:
    if "ECHO:" not in line:
        raise ValueError("line is not an OpenSCAD echo")

    payload = line.split("ECHO:", 1)[1].strip()
    fields = _split_top_level_fields(payload)
    if not fields:
        raise ValueError("echo payload is empty")

    label_raw, *kv_pairs = fields
    label = label_raw.strip().strip('"')
    values: dict[str, Any] = {}

    for pair in kv_pairs:
        if "=" not in pair:
            raise ValueError(f"malformed key/value pair: {pair}")
        key, raw_value = pair.split("=", 1)
        values[key.strip()] = _parse_value(raw_value)

    return EchoLine(label=label, values=values, raw=line)


def run_openscad_and_capture_echoes(
    scad_path: Path, defs: list[str], out_path: Path
) -> OpenScadRunResult:
    cmd = ["openscad", "-o", str(out_path)]
    for definition in defs:
        cmd.extend(["-D", definition])
    cmd.append(str(scad_path))

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    echo_lines = [
        parse_echo_line(line) for line in result.stderr.splitlines() if "ECHO:" in line
    ]

    return OpenScadRunResult(stdout=result.stdout, stderr=result.stderr, echo_lines=echo_lines)
