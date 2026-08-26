#!/usr/bin/env python3
"""Validate Prometheus' effective, loaded TSDB retention policy."""

import json
import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def parse_prometheus_size(value: str) -> int:
    """Parse the binary storage units accepted and reported by Prometheus."""
    match = re.fullmatch(r"([0-9]+)([KMGTPE]?i?B)", value.strip())
    if not match:
        raise ValueError(value)
    exponent = {
        "B": 0,
        "KB": 1,
        "KiB": 1,
        "MB": 2,
        "MiB": 2,
        "GB": 3,
        "GiB": 3,
        "TB": 4,
        "TiB": 4,
        "PB": 5,
        "PiB": 5,
        "EB": 6,
        "EiB": 6,
    }[match.group(2)]
    return int(match.group(1)) * 1024**exponent


def parse_days(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)d", value.strip())
    if not match:
        raise ValueError(value)
    return int(match.group(1))


def loaded_retention(yaml_text: str) -> tuple[str, str]:
    """Read storage.tsdb.retention.{time,size} from Prometheus' YAML."""
    path: list[tuple[int, str]] = []
    found: dict[str, str] = {}
    for raw_line in yaml_text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)([A-Za-z0-9_.-]+):(?:\s*(.*?)\s*)?$", raw_line)
        if not match:
            continue
        indent, key, value = len(match.group(1)), match.group(2), match.group(3)
        while path and path[-1][0] >= indent:
            path.pop()
        full_path = tuple(item[1] for item in path) + (key,)
        if (
            full_path
            in (("storage", "tsdb", "retention", "time"), ("storage", "tsdb", "retention", "size"))
            and value
        ):
            found[key] = value.strip("\"'")
        if not value:
            path.append((indent, key))
    try:
        return found["time"], found["size"]
    except KeyError:
        fail("Prometheus loaded configuration is missing storage.tsdb.retention time or size.")


def load_success_response(path: Path, endpoint: str):
    try:
        response = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail(f"Prometheus {endpoint} response is malformed.")
    if not isinstance(response, dict) or response.get("status") != "success":
        fail(f"Prometheus {endpoint} response is unsuccessful or malformed.")
    return response.get("data")


def validate(
    config_path: Path, runtime_path: Path, metrics_path: Path, desired_time: str, desired_size: str
) -> None:
    config_data = load_success_response(config_path, "status/config")
    runtime_data = load_success_response(runtime_path, "status/runtimeinfo")
    if not isinstance(config_data, dict) or not isinstance(config_data.get("yaml"), str):
        fail("Prometheus status/config response is malformed.")
    if not isinstance(runtime_data, dict):
        fail("Prometheus status/runtimeinfo response is malformed.")
    if runtime_data.get("reloadConfigSuccess") is not True:
        fail("Prometheus configuration reload status is not successful.")

    effective_time, effective_size = loaded_retention(config_data["yaml"])
    try:
        if parse_days(effective_time) != parse_days(desired_time):
            fail(
                f"Prometheus effective time retention is {effective_time}, expected {desired_time}."
            )
    except ValueError:
        fail(f"Prometheus time retention is invalid: {effective_time}.")
    try:
        desired_bytes = parse_prometheus_size(desired_size)
        effective_bytes = parse_prometheus_size(effective_size)
    except ValueError as error:
        fail(f"Prometheus size retention is invalid: {error.args[0]}.")
    if effective_bytes != desired_bytes:
        fail(
            f"Prometheus effective size retention is {effective_size}, "
            f"expected {desired_size} ({desired_bytes} bytes)."
        )

    try:
        metrics = metrics_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        fail("Prometheus metrics response is malformed.")
    matches = re.findall(
        r"(?m)^prometheus_tsdb_retention_limit_bytes\s+([0-9]+(?:\.[0-9]+)?)$", metrics
    )
    if len(matches) != 1:
        fail("Prometheus runtime size-retention byte limit is missing or ambiguous.")
    runtime_bytes = float(matches[0])
    if runtime_bytes <= 0 or runtime_bytes != desired_bytes:
        fail(
            f"Prometheus runtime size-retention limit is {matches[0]} bytes, "
            f"expected {desired_bytes}."
        )


if __name__ == "__main__":
    if len(sys.argv) != 6:
        fail("usage: verify_prometheus_retention.py CONFIG RUNTIME METRICS TIME SIZE")
    validate(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5])
