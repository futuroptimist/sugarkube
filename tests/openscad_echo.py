from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterable


def _format_definition(definitions: dict[str, Any] | Iterable[str]) -> list[str]:
    if isinstance(definitions, dict):
        defs: list[str] = []
        for key, value in definitions.items():
            defs.append(f"{key}={_format_value(value)}")
        return defs

    return list(definitions)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def run_openscad_collect_echoes(
    scad_path: Path, tmp_path: Path, definitions: dict[str, Any] | Iterable[str]
) -> list[str]:
    """Run OpenSCAD against ``scad_path`` and return emitted ``ECHO:`` lines."""

    out_file = tmp_path / f"{scad_path.stem}.stl"
    cmd = ["openscad", "-o", str(out_file)]
    for definition in _format_definition(definitions):
        cmd.extend(["-D", definition])
    cmd.append(str(scad_path))

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [line for line in result.stderr.splitlines() if "ECHO:" in line]


def last_echo_with_label(echo_lines: list[str], label: str) -> str:
    """Return the last echo containing ``label`` or raise a clear error."""

    matches = [line for line in echo_lines if f'"{label}"' in line]
    if not matches:
        raise ValueError(f"Label '{label}' not found in echo output")
    return matches[-1]


def parse_echo_key_values(echo_line: str, label: str | None = None) -> dict[str, Any]:
    """Parse a single ``ECHO:`` line into a dict of key/value pairs."""

    if "ECHO:" not in echo_line:
        raise ValueError("Line is not an OpenSCAD ECHO")

    content = echo_line.split("ECHO:", 1)[1].strip()
    segments = _split_segments(content)
    if not segments:
        raise ValueError("ECHO line did not contain label content")

    label_text = segments.pop(0)
    resolved_label = label_text.strip().strip('"')
    if label and resolved_label != label:
        raise ValueError(f"Expected label '{label}', got '{resolved_label}'")

    parsed: dict[str, Any] = {}
    for segment in segments:
        if "=" not in segment:
            raise ValueError(f"Malformed segment: {segment}")
        key, value = segment.split("=", 1)
        parsed[key.strip()] = _parse_value(value.strip())

    return parsed


def _split_segments(content: str) -> list[str]:
    segments: list[str] = []
    current = []
    depth = 0

    for char in content:
        if char == "," and depth == 0:
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        current.append(char)

    trailing = "".join(current).strip()
    if trailing:
        segments.append(trailing)

    return segments


def _parse_value(raw_value: str) -> Any:
    if raw_value.startswith("[") and raw_value.endswith("]"):
        return _parse_array(raw_value)
    if raw_value in {"true", "false"}:
        return raw_value == "true"
    if raw_value.lstrip("-+.").isdigit() and "." not in raw_value and "e" not in raw_value.lower():
        return int(raw_value)
    if _is_float(raw_value):
        return float(raw_value)
    if (raw_value.startswith("\"") and raw_value.endswith("\"")) or (
        raw_value.startswith("'") and raw_value.endswith("'")
    ):
        return raw_value[1:-1]
    if raw_value.isidentifier():
        return raw_value
    raise ValueError(f"Unsupported value: {raw_value}")


def _parse_array(raw_value: str) -> list[Any]:
    inner = raw_value[1:-1].strip()
    if not inner:
        return []

    elements: list[str] = []
    current = []
    depth = 0
    for char in inner:
        if char == "," and depth == 0:
            element = "".join(current).strip()
            if element:
                elements.append(element)
            current = []
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        current.append(char)

    trailing = "".join(current).strip()
    if trailing:
        elements.append(trailing)

    return [_parse_value(element) for element in elements]


def _is_float(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
