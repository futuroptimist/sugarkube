from __future__ import annotations

import ast
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

OPENSCAD = shutil.which("openscad")


@dataclass
class OpenSCADResult:
    stderr: str
    echo_lines: list[str]

    def last_echo_line(self, label: str) -> str:
        """Return the last echo line containing the requested label."""

        matches = [line for line in self.echo_lines if f'"{label}"' in line]
        if not matches:
            raise ValueError(f"No echo lines found for label '{label}'")
        return matches[-1]

    def last_echo_dict(self, label: str) -> dict[str, Any]:
        """Return the parsed dictionary for the last echo matching the label."""

        return parse_echo_dict(self.last_echo_line(label), label)


def run_openscad_with_defs(
    scad_path: Path, defs: Iterable[str], output_path: Path
) -> OpenSCADResult:
    """Run OpenSCAD with definitions and capture echo output."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["openscad", "-o", str(output_path)]
    for definition in defs:
        cmd.extend(["-D", definition])
    cmd.append(str(scad_path))

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    echo_lines = [line for line in result.stderr.splitlines() if "ECHO:" in line]
    return OpenSCADResult(stderr=result.stderr, echo_lines=echo_lines)


def parse_echo_dict(line: str, label: str) -> dict[str, Any]:
    """Parse a single echo line into a dictionary of key/value pairs."""

    if "ECHO:" not in line:
        raise ValueError("Line does not contain an OpenSCAD ECHO prefix")

    _, _, body = line.partition("ECHO:")
    body = body.strip()
    if f'"{label}"' not in body:
        raise ValueError(f"Expected label '{label}' in echo line: {body}")

    # Remove the label prefix, leaving the comma-delimited key/value pairs.
    _, _, remainder = body.partition(",")
    if not remainder:
        return {}

    entries = _split_key_value_segments(remainder)
    parsed = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Malformed echo entry (missing '='): {entry}")
        key, raw_value = entry.split("=", 1)
        parsed[key.strip()] = _parse_value(raw_value.strip())
    return parsed


def _split_key_value_segments(segment: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for char in segment:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_value(value: str) -> Any:
    normalized = value
    for source, target in {"true": "True", "false": "False", "undef": "None"}.items():
        normalized = re.sub(rf"\b{source}\b", target, normalized)

    if normalized.startswith("["):
        return ast.literal_eval(normalized)

    if normalized.startswith("\"") or normalized.startswith("'"):
        return ast.literal_eval(normalized)

    for converter in (int, float):
        try:
            return converter(normalized)
        except ValueError:
            continue

    if normalized in ("True", "False"):
        return normalized == "True"
    if normalized == "None":
        return None

    try:
        return ast.literal_eval(normalized)
    except Exception as exc:  # noqa: BLE001
        if normalized.isidentifier():
            return normalized
        raise ValueError(f"Could not parse value: {value}") from exc
