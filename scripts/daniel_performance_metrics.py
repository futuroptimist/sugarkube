#!/usr/bin/env python3
"""Render the bounded PerformanceResultV1 contract as Prometheus textfile metrics."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from pathlib import Path

MAX_PAYLOAD_BYTES = 64 * 1024
MAX_DURATION_MS = 3_600_000
MAX_SAMPLES = 10_000
MAX_BUILD_TAG_LENGTH = 80
RESULT_STATES = ("completed", "regression", "unavailable")
RENDERER_CLASSES = ("hardware", "software", "unknown")
RENDERER_STATES = ("immersive", "fallback", "unavailable")
FALLBACK_REASONS = ("none", "unsupported_webgl", "software_renderer", "performance", "unknown")
MEASUREMENT_STATES = ("available", "unavailable")
UNAVAILABLE_REASONS = ("none", "not_collected", "unsupported_environment", "renderer_fallback")
BUILD_TAG = re.compile(r"[A-Za-z0-9._:-]{1,80}")


def _exact(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _duration(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and 0 <= value <= MAX_DURATION_MS
    )


def _summary(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("state") == "unavailable":
        return _exact(value, {"state", "reason"}) and value["reason"] in UNAVAILABLE_REASONS[1:]
    return (
        _exact(value, {"state", "sampleCount", "medianMs", "p95Ms", "maxMs"})
        and value["state"] == "available"
        and _integer(value["sampleCount"], 1, MAX_SAMPLES)
        and all(_duration(value[key]) for key in ("medianMs", "p95Ms", "maxMs"))
        and value["medianMs"] <= value["p95Ms"] <= value["maxMs"]
    )


def parse_result(payload: bytes, environment: str) -> dict:
    """Validate the exact app-owned contract without retaining arbitrary input."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("performance result exceeds the bounded payload size")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("performance result is malformed") from error
    top = {
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
    }
    if not _exact(value, top):
        raise ValueError("performance result does not match schema version 1")
    build, runtime, conditions, renderer = (
        value["build"],
        value["environment"],
        value["conditions"],
        value["renderer"],
    )
    valid = (
        value["schemaVersion"] == 1
        and value["state"] in RESULT_STATES
        and _integer(value["measuredAt"], 0, 2**53 - 1)
        and _exact(build, {"environment", "tag"})
        and build["environment"] in {"dev", "staging", "prod"}
        and build["environment"] == environment
        and isinstance(build["tag"], str)
        and len(build["tag"]) <= MAX_BUILD_TAG_LENGTH
        and BUILD_TAG.fullmatch(build["tag"]) is not None
        and _exact(
            runtime,
            {
                "browser",
                "browserMajorVersion",
                "viewportWidth",
                "viewportHeight",
                "renderingMode",
                "rendererClass",
                "frameMeasurementProfile",
            },
        )
        and runtime["browser"] in {"chromium", "firefox", "webkit"}
        and _integer(runtime["browserMajorVersion"], 1, 999)
        and _integer(runtime["viewportWidth"], 1, 10_000)
        and _integer(runtime["viewportHeight"], 1, 10_000)
        and runtime["renderingMode"] in {"immersive", "fallback"}
        and runtime["rendererClass"] in RENDERER_CLASSES
        and runtime["frameMeasurementProfile"] in {"controlled_hardware_v1", "unsupported"}
        and _exact(
            conditions,
            {
                "warmupMs",
                "interactionName",
                "requestedActions",
                "eventsPerAction",
                "requestedSamples",
            },
        )
        and _duration(conditions["warmupMs"])
        and conditions["interactionName"] == "keyboard_movement"
        and _integer(conditions["requestedActions"], 1, MAX_SAMPLES)
        and conditions["eventsPerAction"] == 2
        and _integer(conditions["requestedSamples"], 1, MAX_SAMPLES)
        and conditions["requestedSamples"] == conditions["requestedActions"] * 2
        and _exact(renderer, {"state", "fallbackReason"})
        and renderer["state"] in RENDERER_STATES
        and renderer["fallbackReason"] in FALLBACK_REASONS
        and all(
            _summary(value[key]) for key in ("applicationReady", "interactionLatency", "frameTime")
        )
    )
    if not valid:
        raise ValueError("performance result contains an invalid bounded value")
    required_unavailable = any(
        value[key]["state"] == "unavailable" for key in ("applicationReady", "interactionLatency")
    )
    hardware = (
        runtime["browser"] == "chromium"
        and runtime["renderingMode"] == "immersive"
        and runtime["rendererClass"] == "hardware"
        and runtime["frameMeasurementProfile"] == "controlled_hardware_v1"
        and renderer == {"state": "immersive", "fallbackReason": "none"}
    )
    contradictory = (
        (value["state"] == "unavailable") != required_unavailable
        or (
            renderer["state"] == "immersive"
            and (runtime["renderingMode"] != "immersive" or renderer["fallbackReason"] != "none")
        )
        or (
            renderer["state"] == "fallback"
            and (runtime["renderingMode"] != "fallback" or renderer["fallbackReason"] == "none")
        )
        or (renderer["state"] == "unavailable" and renderer["fallbackReason"] == "none")
        or (
            value["interactionLatency"]["state"] == "available"
            and value["interactionLatency"]["sampleCount"] != conditions["requestedSamples"]
        )
        or (
            value["frameTime"]["state"] == "available"
            and (not hardware or value["frameTime"]["sampleCount"] != 120)
        )
        or (runtime["frameMeasurementProfile"] == "controlled_hardware_v1" and not hardware)
    )
    if contradictory:
        raise ValueError("performance result is internally inconsistent")
    return value


def _one_hot(
    name: str, domain: tuple[str, ...], selected: str, label: str, environment: str
) -> list[str]:
    return [
        f'{name}{{environment="{environment}",{label}="{item}"}} {int(item == selected)}'
        for item in domain
    ]


def render(payload: bytes, environment: str) -> str:
    value = parse_result(payload, environment)
    lines = [
        "# HELP daniel_performance_collection_up Whether the bounded result was accepted.",
        "# TYPE daniel_performance_collection_up gauge",
        f'daniel_performance_collection_up{{environment="{environment}"}} 1',
    ]
    lines += _one_hot(
        "daniel_performance_result_state", RESULT_STATES, value["state"], "state", environment
    )
    lines += _one_hot(
        "daniel_performance_renderer_class",
        RENDERER_CLASSES,
        value["environment"]["rendererClass"],
        "renderer_class",
        environment,
    )
    lines += _one_hot(
        "daniel_performance_renderer_state",
        RENDERER_STATES,
        value["renderer"]["state"],
        "renderer_state",
        environment,
    )
    lines += _one_hot(
        "daniel_performance_fallback",
        FALLBACK_REASONS,
        value["renderer"]["fallbackReason"],
        "fallback_reason",
        environment,
    )
    build_environment = value["build"]["environment"]
    build_tag = value["build"]["tag"]
    measured_at = value["measuredAt"]
    lines += [
        "daniel_performance_build_info"
        f'{{environment="{environment}",build_environment="{build_environment}",'
        f'build_tag="{build_tag}"}} 1',
        "daniel_performance_measured_timestamp_seconds"
        f'{{environment="{environment}"}} {measured_at}',
    ]
    for key, metric in (
        ("applicationReady", "application_ready"),
        ("interactionLatency", "interaction_latency"),
        ("frameTime", "frame_time"),
    ):
        summary = value[key]
        reason = summary.get("reason", "none")
        lines += _one_hot(
            "daniel_performance_measurement_state",
            MEASUREMENT_STATES,
            summary["state"],
            "state",
            environment,
        )
        # Add the measurement dimension after construction; its domain is fixed by this loop.
        lines[-2:] = [
            line.replace("{environment=", f'{{measurement="{metric}",environment=')
            for line in lines[-2:]
        ]
        lines += _one_hot(
            "daniel_performance_measurement_unavailable",
            UNAVAILABLE_REASONS,
            reason,
            "reason",
            environment,
        )
        lines[-4:] = [
            line.replace("{environment=", f'{{measurement="{metric}",environment=')
            for line in lines[-4:]
        ]
        if summary["state"] == "available":
            sample_count = summary["sampleCount"]
            lines.append(
                f"daniel_performance_{metric}_samples"
                f'{{environment="{environment}"}} {sample_count}'
            )
            for statistic in ("median", "p95", "max"):
                seconds = summary[statistic + "Ms"] / 1000
                lines.append(
                    f"daniel_performance_{metric}_seconds"
                    f'{{environment="{environment}",statistic="{statistic}"}} {seconds:g}'
                )
    return "\n".join(lines) + "\n"


def failure_metrics(environment: str) -> str:
    return f'daniel_performance_collection_up{{environment="{environment}"}} 0\n'


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
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--environment", required=True, choices=("staging", "prod"))
    args = parser.parse_args()
    try:
        payload = args.result.read_bytes()
        content = render(payload, args.environment)
    except (OSError, ValueError):
        content = failure_metrics(args.environment)
        write_textfile(args.output, content)
        return 1
    write_textfile(args.output, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
