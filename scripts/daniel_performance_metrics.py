#!/usr/bin/env python3
"""Convert a controlled Daniel PerformanceResultV1 into bounded textfile metrics."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from pathlib import Path

MAX_BYTES = 65_536
MAX_DURATION_MS = 3_600_000
MAX_SAMPLES = 10_000
RESULT_STATES = ("completed", "regression", "unavailable")
RENDERER_CLASSES = ("hardware", "software", "unknown")
RENDERER_STATES = ("immersive", "fallback", "unavailable")
FALLBACK_REASONS = ("none", "unsupported_webgl", "software_renderer", "performance", "unknown")
DOCUMENT_STATUSES = ("valid", "malformed", "oversized", "unavailable")
SUMMARY_REASONS = ("not_collected", "unsupported_environment", "renderer_fallback")
BUILD_TAG = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


class InvalidResult(ValueError):
    """The input does not match PerformanceResultV1 exactly."""


def _exact(value: object, keys: set[str], field: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidResult(field)
    return value


def _integer(value: object, low: int, high: int, field: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise InvalidResult(field)
    return value


def _duration(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidResult(field)
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= MAX_DURATION_MS:
        raise InvalidResult(field)
    return number


def _summary(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise InvalidResult(field)
    if value.get("state") == "unavailable":
        result = _exact(value, {"state", "reason"}, field)
        if result["reason"] not in SUMMARY_REASONS:
            raise InvalidResult(field)
        return result
    result = _exact(value, {"state", "sampleCount", "medianMs", "p95Ms", "maxMs"}, field)
    if result["state"] != "available":
        raise InvalidResult(field)
    _integer(result["sampleCount"], 1, MAX_SAMPLES, field)
    values = [_duration(result[name], field) for name in ("medianMs", "p95Ms", "maxMs")]
    if values != sorted(values):
        raise InvalidResult(field)
    return result


def parse_result(payload: bytes, environment: str) -> dict:
    """Validate the exact application-owned v1 contract and its relationships."""
    if len(payload) > MAX_BYTES:
        raise OverflowError("performance result exceeds 65536 bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise InvalidResult("JSON") from error
    value = _exact(
        value,
        {
            "schemaVersion",
            "state",
            "measuredAt",
            "build",
            "environment",
            "conditions",
            "renderer",
            "applicationReady",
            "interactionLatency",
            "frameTime",
        },
        "result",
    )
    if value["schemaVersion"] != 1 or value["state"] not in RESULT_STATES:
        raise InvalidResult("schema/state")
    _integer(value["measuredAt"], 0, 9_007_199_254_740_991, "measuredAt")
    build = _exact(value["build"], {"environment", "tag"}, "build")
    if (
        build["environment"] != environment
        or not isinstance(build["tag"], str)
        or not BUILD_TAG.fullmatch(build["tag"])
    ):
        raise InvalidResult("build identity")
    env = _exact(
        value["environment"],
        {
            "browser",
            "browserMajorVersion",
            "viewportWidth",
            "viewportHeight",
            "renderingMode",
            "rendererClass",
            "frameMeasurementProfile",
        },
        "environment",
    )
    if (
        env["browser"] not in ("chromium", "firefox", "webkit")
        or env["renderingMode"] not in ("immersive", "fallback")
        or env["rendererClass"] not in RENDERER_CLASSES
        or env["frameMeasurementProfile"] not in ("controlled_hardware_v1", "unsupported")
    ):
        raise InvalidResult("environment enums")
    for name, maximum in (
        ("browserMajorVersion", 999),
        ("viewportWidth", 10_000),
        ("viewportHeight", 10_000),
    ):
        _integer(env[name], 1, maximum, name)
    conditions = _exact(
        value["conditions"],
        {"warmupMs", "interactionName", "requestedActions", "eventsPerAction", "requestedSamples"},
        "conditions",
    )
    _duration(conditions["warmupMs"], "warmupMs")
    actions = _integer(conditions["requestedActions"], 1, MAX_SAMPLES, "requestedActions")
    samples = _integer(conditions["requestedSamples"], 1, MAX_SAMPLES, "requestedSamples")
    if (
        conditions["interactionName"] != "keyboard_movement"
        or conditions["eventsPerAction"] != 2
        or samples != actions * 2
    ):
        raise InvalidResult("interaction conditions")
    renderer = _exact(value["renderer"], {"state", "fallbackReason"}, "renderer")
    if (
        renderer["state"] not in RENDERER_STATES
        or renderer["fallbackReason"] not in FALLBACK_REASONS
    ):
        raise InvalidResult("renderer enums")
    if renderer["state"] == "immersive" and (
        env["renderingMode"] != "immersive" or renderer["fallbackReason"] != "none"
    ):
        raise InvalidResult("renderer relationship")
    if renderer["state"] == "fallback" and (
        env["renderingMode"] != "fallback" or renderer["fallbackReason"] == "none"
    ):
        raise InvalidResult("fallback relationship")
    if renderer["state"] == "unavailable" and renderer["fallbackReason"] == "none":
        raise InvalidResult("unavailable renderer relationship")
    summaries = {
        name: _summary(value[name], name)
        for name in ("applicationReady", "interactionLatency", "frameTime")
    }
    required_unavailable = any(
        summaries[name]["state"] == "unavailable"
        for name in ("applicationReady", "interactionLatency")
    )
    if (value["state"] == "unavailable") != required_unavailable:
        raise InvalidResult("result relationship")
    if (
        summaries["interactionLatency"]["state"] == "available"
        and summaries["interactionLatency"]["sampleCount"] != samples
    ):
        raise InvalidResult("interaction sample count")
    frame_supported = (
        env["browser"] == "chromium"
        and env["rendererClass"] == "hardware"
        and env["frameMeasurementProfile"] == "controlled_hardware_v1"
        and renderer == {"state": "immersive", "fallbackReason": "none"}
    )
    if summaries["frameTime"]["state"] == "available" and (
        not frame_supported or summaries["frameTime"]["sampleCount"] != 120
    ):
        raise InvalidResult("frame support")
    if env["frameMeasurementProfile"] == "controlled_hardware_v1" and not frame_supported:
        raise InvalidResult("frame profile")
    value["summaries"] = summaries
    return value


def render(payload: bytes | None, environment: str, status: str = "valid") -> str:
    result = parse_result(payload, environment) if payload is not None else None
    lines = [
        "# HELP daniel_performance_collection_up Whether a result was present and valid.",
        "# TYPE daniel_performance_collection_up gauge",
        f'daniel_performance_collection_up{{environment="{environment}"}} '
        f"{int(result is not None)}",
    ]
    selected_state = result["state"] if result else "unavailable"
    for metric, domain, selected, label in (
        ("daniel_performance_document_status", DOCUMENT_STATUSES, status, "status"),
        ("daniel_performance_result_state", RESULT_STATES, selected_state, "state"),
        (
            "daniel_performance_renderer_class",
            RENDERER_CLASSES,
            result["environment"]["rendererClass"] if result else "unknown",
            "renderer_class",
        ),
        (
            "daniel_performance_renderer_state",
            RENDERER_STATES,
            result["renderer"]["state"] if result else "unavailable",
            "renderer_state",
        ),
        (
            "daniel_performance_fallback_reason",
            FALLBACK_REASONS,
            result["renderer"]["fallbackReason"] if result else "unknown",
            "fallback_reason",
        ),
    ):
        lines.extend(
            f'{metric}{{environment="{environment}",{label}="{item}"}} {int(item == selected)}'
            for item in domain
        )
    if result:
        lines.append(
            f'daniel_performance_build_info{{environment="{environment}",'
            f'build_tag="{result["build"]["tag"]}"}} 1'
        )
        lines.append(
            "daniel_performance_measured_timestamp_seconds"
            f'{{environment="{environment}"}} {result["measuredAt"]}'
        )
        for name, metric in (
            ("applicationReady", "application_ready"),
            ("interactionLatency", "interaction_latency"),
            ("frameTime", "frame_time"),
        ):
            summary = result["summaries"][name]
            if summary["state"] == "available":
                for stat, key in (("median", "medianMs"), ("p95", "p95Ms"), ("max", "maxMs")):
                    lines.append(
                        f'daniel_performance_{metric}_seconds{{environment="{environment}",'
                        f'stat="{stat}"}} {summary[key] / 1000:g}'
                    )
    return "\n".join(lines) + "\n"


def collect(path: Path | None, environment: str) -> str:
    if path is None or not path.is_file():
        return render(None, environment, "unavailable")
    try:
        payload = path.read_bytes()
        return render(payload, environment)
    except OverflowError:
        return render(None, environment, "oversized")
    except (OSError, InvalidResult):
        return render(None, environment, "malformed")


def write_textfile(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".daniel-performance-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_textfile(args.output, collect(args.result, args.environment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
