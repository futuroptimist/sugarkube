#!/usr/bin/env python3
"""Convert a Daniel controlled-performance result to bounded Prometheus metrics."""

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
RENDERING_MODES = ("immersive", "fallback")
RENDERER_CLASSES = ("hardware", "software", "unknown")
RENDERER_STATES = ("immersive", "fallback", "unavailable")
FALLBACK_REASONS = ("none", "unsupported_webgl", "software_renderer", "performance", "unknown")
UNAVAILABLE_REASONS = ("not_collected", "unsupported_environment", "renderer_fallback")
BUILD_ENVIRONMENTS = ("dev", "staging", "prod")
BROWSERS = ("chromium", "firefox", "webkit")
FRAME_PROFILES = ("controlled_hardware_v1", "unsupported")
BUILD_TAG = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


class InvalidResult(ValueError):
    """The payload is not the exact PerformanceResultV1 contract."""


def _exact(value, keys, field):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise InvalidResult(field)
    return value


def _integer(value, minimum, maximum, field):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidResult(field)
    return value


def _duration(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidResult(field)
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= MAX_DURATION_MS:
        raise InvalidResult(field)
    return number


def _summary(value, field):
    if not isinstance(value, dict):
        raise InvalidResult(field)
    if value.get("state") == "unavailable":
        _exact(value, ("state", "reason"), field)
        if value["reason"] not in UNAVAILABLE_REASONS:
            raise InvalidResult(field)
        return {"state": "unavailable", "reason": value["reason"]}
    _exact(value, ("state", "sampleCount", "medianMs", "p95Ms", "maxMs"), field)
    if value["state"] != "available":
        raise InvalidResult(field)
    count = _integer(value["sampleCount"], 1, MAX_SAMPLES, field)
    median = _duration(value["medianMs"], field)
    p95 = _duration(value["p95Ms"], field)
    maximum = _duration(value["maxMs"], field)
    if not median <= p95 <= maximum:
        raise InvalidResult(field)
    return {
        "state": "available",
        "sampleCount": count,
        "medianMs": median,
        "p95Ms": p95,
        "maxMs": maximum,
    }


def parse(payload: bytes) -> dict:
    if len(payload) > MAX_BYTES:
        raise OverflowError("performance result exceeds 65536 bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise InvalidResult("JSON") from exc
    _exact(
        value,
        (
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
        ),
        "result",
    )
    if value["schemaVersion"] != 1 or value["state"] not in RESULT_STATES:
        raise InvalidResult("version/state")
    _integer(value["measuredAt"], 0, 9_007_199_254_740_991, "measuredAt")
    build = _exact(value["build"], ("environment", "tag"), "build")
    if (
        build["environment"] not in BUILD_ENVIRONMENTS
        or not isinstance(build["tag"], str)
        or not BUILD_TAG.fullmatch(build["tag"])
    ):
        raise InvalidResult("build")
    environment = _exact(
        value["environment"],
        (
            "browser",
            "browserMajorVersion",
            "viewportWidth",
            "viewportHeight",
            "renderingMode",
            "rendererClass",
            "frameMeasurementProfile",
        ),
        "environment",
    )
    if (
        environment["browser"] not in BROWSERS
        or environment["renderingMode"] not in RENDERING_MODES
        or environment["rendererClass"] not in RENDERER_CLASSES
        or environment["frameMeasurementProfile"] not in FRAME_PROFILES
    ):
        raise InvalidResult("environment")
    _integer(environment["browserMajorVersion"], 1, 999, "browser")
    _integer(environment["viewportWidth"], 1, 10_000, "viewport")
    _integer(environment["viewportHeight"], 1, 10_000, "viewport")
    conditions = _exact(
        value["conditions"],
        ("warmupMs", "interactionName", "requestedActions", "eventsPerAction", "requestedSamples"),
        "conditions",
    )
    _duration(conditions["warmupMs"], "warmup")
    actions = _integer(conditions["requestedActions"], 1, MAX_SAMPLES, "actions")
    samples = _integer(conditions["requestedSamples"], 1, MAX_SAMPLES, "samples")
    if (
        conditions["interactionName"] != "keyboard_movement"
        or conditions["eventsPerAction"] != 2
        or samples != actions * 2
    ):
        raise InvalidResult("conditions")
    renderer = _exact(value["renderer"], ("state", "fallbackReason"), "renderer")
    if (
        renderer["state"] not in RENDERER_STATES
        or renderer["fallbackReason"] not in FALLBACK_REASONS
    ):
        raise InvalidResult("renderer")
    if renderer["state"] == "immersive" and (
        environment["renderingMode"] != "immersive" or renderer["fallbackReason"] != "none"
    ):
        raise InvalidResult("renderer")
    if renderer["state"] == "fallback" and (
        environment["renderingMode"] != "fallback" or renderer["fallbackReason"] == "none"
    ):
        raise InvalidResult("renderer")
    if renderer["state"] == "unavailable" and renderer["fallbackReason"] == "none":
        raise InvalidResult("renderer")
    ready = _summary(value["applicationReady"], "applicationReady")
    latency = _summary(value["interactionLatency"], "interactionLatency")
    frame = _summary(value["frameTime"], "frameTime")
    unavailable = ready["state"] == "unavailable" or latency["state"] == "unavailable"
    if (value["state"] == "unavailable") != unavailable or (
        value["state"] == "regression" and unavailable
    ):
        raise InvalidResult("result relationship")
    supported = (
        environment["browser"] == "chromium"
        and environment["renderingMode"] == "immersive"
        and environment["rendererClass"] == "hardware"
        and environment["frameMeasurementProfile"] == "controlled_hardware_v1"
        and renderer == {"state": "immersive", "fallbackReason": "none"}
    )
    if environment["frameMeasurementProfile"] == "controlled_hardware_v1" and not supported:
        raise InvalidResult("frame profile")
    if frame["state"] == "available" and (not supported or frame["sampleCount"] != 120):
        raise InvalidResult("frameTime")
    if latency["state"] == "available" and latency["sampleCount"] != samples:
        raise InvalidResult("interactionLatency")
    value.update(applicationReady=ready, interactionLatency=latency, frameTime=frame)
    return value


def render(payload: bytes, environment: str) -> str:
    if environment not in ("staging", "prod"):
        raise ValueError("unsupported collection environment")
    result = parse(payload)
    if result["build"]["environment"] != environment:
        raise InvalidResult("build environment does not match collection environment")
    base = f'environment="{environment}"'
    lines = [
        "# HELP daniel_performance_collection_up Whether PerformanceResultV1 was validated.",
        "# TYPE daniel_performance_collection_up gauge",
        f"daniel_performance_collection_up{{{base}}} 1",
    ]
    for metric, domain, selected, label in (
        ("daniel_performance_result_state", RESULT_STATES, result["state"], "state"),
        (
            "daniel_performance_fallback_status",
            FALLBACK_REASONS,
            result["renderer"]["fallbackReason"],
            "fallback_status",
        ),
    ):
        lines.extend(
            f'{metric}{{{base},{label}="{item}"}} {int(item == selected)}' for item in domain
        )
    lines.append(
        f'daniel_performance_renderer_info{{{base},'
        f'renderer_mode="{result["environment"]["renderingMode"]}",'
        f'renderer_class="{result["environment"]["rendererClass"]}"}} 1'
    )
    lines.append(
        f'daniel_performance_build_info{{{base},'
        f'build_environment="{result["build"]["environment"]}",'
        f'build_tag="{result["build"]["tag"]}"}} 1'
    )
    lines.append(f'daniel_performance_measured_timestamp_seconds{{{base}}} {result["measuredAt"]}')
    for metric, key in (
        ("application_ready", "applicationReady"),
        ("interaction_latency", "interactionLatency"),
        ("frame_time", "frameTime"),
    ):
        summary = result[key]
        if summary["state"] == "available":
            lines.append(f'daniel_performance_{metric}_samples{{{base}}} {summary["sampleCount"]}')
            for statistic, source in (("median", "medianMs"), ("p95", "p95Ms"), ("max", "maxMs")):
                lines.append(
                    f'daniel_performance_{metric}_seconds{{{base},'
                    f'statistic="{statistic}"}} {summary[source] / 1000:g}'
                )
    return "\n".join(lines) + "\n"


def write_textfile(path: Path, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".daniel-performance-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = args.input.read_bytes()
    try:
        output = render(payload, args.environment)
    except (InvalidResult, OverflowError):
        output = f'daniel_performance_collection_up{{environment="{args.environment}"}} 0\n'
    write_textfile(args.output, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
