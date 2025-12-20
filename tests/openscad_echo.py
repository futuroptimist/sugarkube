"""Helpers for capturing and parsing OpenSCAD echo output."""

from __future__ import annotations

import ast
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Mapping


def _format_value(value: object) -> str:
    """Format a Python value for an OpenSCAD `-D` definition.

    Parameters
    ----------
    value: object
        The value to format. Supported types are ``bool``, ``int``, ``float``,
        and ``str`` (pre-quoted strings are preserved).

    Returns
    -------
    str
        The value converted into an OpenSCAD-compatible literal.

    Raises
    ------
    TypeError
        If ``value`` is not one of the supported types.
    """

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Preserve already-quoted strings to avoid double quoting.
        return value if value.startswith("\"") and value.endswith("\"") else f'"{value}"'
    raise TypeError(f"Unsupported definition value type: {type(value)}")


def _format_definitions(definitions: Mapping[str, object] | Iterable[str]) -> list[str]:
    """Normalize OpenSCAD ``-D`` definitions into ``key=value`` strings.

    Parameters
    ----------
    definitions: Mapping[str, object] | Iterable[str]
        Either a mapping of definition names to values (formatted via
        :func:`_format_value`) or an iterable of preformatted definition
        strings.

    Returns
    -------
    list[str]
        A list of strings suitable for passing to OpenSCAD via ``-D`` flags.
    """

    if isinstance(definitions, Mapping):
        return [f"{key}={_format_value(value)}" for key, value in definitions.items()]

    return list(definitions)


def run_openscad(
    scad_path: Path,
    definitions: Mapping[str, object] | Iterable[str],
    *,
    openscad_path: str,
) -> list[str]:
    """Run OpenSCAD and return raw echo lines from stderr.

    A temporary STL is written to satisfy OpenSCAD's CLI requirements.
    """

    _, stderr = run_openscad_with_output(scad_path, definitions, openscad_path=openscad_path)

    return [line for line in stderr.splitlines() if "ECHO:" in line]


def run_openscad_with_output(
    scad_path: Path,
    definitions: Mapping[str, object] | Iterable[str],
    *,
    openscad_path: str,
) -> tuple[str, str]:
    """Run OpenSCAD and return the full stdout/stderr payloads."""

    with tempfile.TemporaryDirectory(prefix="sugarkube-openscad-") as tmpdir:
        out_file = Path(tmpdir) / "out.stl"
        cmd = [openscad_path, "-o", str(out_file)]
        for definition in _format_definitions(definitions):
            cmd.extend(["-D", definition])
        cmd.append(str(scad_path))

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    return result.stdout, result.stderr


def find_last_echo(echo_lines: list[str], label: str) -> str:
    """Return the last echo line containing the requested label."""

    matches = [line for line in echo_lines if label in line]
    if not matches:
        raise ValueError(f"Label {label!r} not found in echo output")
    return matches[-1]


def _split_fields(raw: str) -> list[str]:
    """Split comma-separated fields while respecting nested brackets.

    Parameters
    ----------
    raw: str
        The substring following an echo label containing comma-delimited
        ``key=value`` fields. Array values may include nested brackets.

    Returns
    -------
    list[str]
        Individual ``key=value`` fields with surrounding whitespace trimmed.

    Raises
    ------
    ValueError
        If unmatched closing brackets are encountered or brackets remain
        unbalanced at the end of parsing. OpenSCAD payloads are expected to be
        well-formed, so mismatches are treated as errors.
    """

    fields: list[str] = []
    depth = 0
    current: list[str] = []

    for char in raw:
        if char == "," and depth == 0:
            if current:
                fields.append("".join(current).strip())
                current = []
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            if depth == 0:
                raise ValueError(f"Unmatched closing bracket in echo payload: {raw!r}")
            depth -= 1
        current.append(char)

    if depth != 0:
        raise ValueError(f"Unbalanced brackets in echo payload: {raw!r}")

    if current:
        fields.append("".join(current).strip())

    return [field for field in fields if field]


def _parse_value(raw_value: str) -> object:
    """Parse an OpenSCAD value string into a Python type.

    Parameters
    ----------
    raw_value: str
        The value portion of a ``key=value`` pair from an echo payload.

    Returns
    -------
    object
        A Python representation of the value (``bool``, ``str``, ``list``,
        ``int``, or ``float``). If parsing fails for an array literal, a
        ``ValueError`` is raised; otherwise the original string is returned as
        a fallback.
    """

    value = raw_value.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith("\"") and value.endswith("\""):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Failed to parse array value {value!r}") from exc
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_echo_line(echo_line: str) -> tuple[str, dict[str, object]]:
    """Parse a single OpenSCAD echo line into a label and key/value dictionary."""

    if "ECHO:" not in echo_line:
        raise ValueError("Line does not contain an OpenSCAD echo")

    _, _, remainder = echo_line.partition("ECHO:")
    remainder = remainder.strip()
    if not remainder.startswith("\""):
        raise ValueError("Echo label missing opening quote")

    end_label = remainder.find("\"", 1)
    if end_label == -1:
        raise ValueError("Echo label missing closing quote")
    label = remainder[1:end_label]

    rest = remainder[end_label + 1 :]
    rest = rest.lstrip(" ,")
    if rest.startswith(":"):
        rest = rest[1:].lstrip()
    if not rest:
        return label, {}

    fields = _split_fields(rest)
    parsed: dict[str, object] = {}
    for field in fields:
        key, sep, value = field.partition("=")
        if sep != "=":
            raise ValueError(f"Malformed echo field: {field}")
        parsed[key.strip()] = _parse_value(value)

    return label, parsed
