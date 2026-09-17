#!/usr/bin/env python3
"""Validate Daniel's passive performance result and render bounded metrics."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

MAX_BYTES = 65_536
MAX_DURATION_MS = 3_600_000
MAX_SAMPLES = 10_000
RESULT_STATES = ("completed", "regression", "unavailable")
DOCUMENT_STATUSES = ("valid", "malformed", "oversized", "unavailable")
RENDERER_CLASSES = ("hardware", "software", "unknown")
RENDERER_STATES = ("immersive", "fallback", "unavailable")
FALLBACK_STATUSES = ("none", "unsupported_webgl", "software_renderer", "performance", "unknown")
MEASUREMENTS = ("application_ready", "interaction_latency", "frame_time")
EVENTS_PER_ACTION = 2
MAX_FUTURE_SKEW_SECONDS = 60
UNAVAILABLE_REASONS = ("none", "not_collected", "unsupported_environment", "renderer_fallback")
BUILD_TAG = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
SUMMARY_KEYS = {"state", "sampleCount", "medianMs", "p95Ms", "maxMs"}
UNAVAILABLE_KEYS = {"state", "reason"}
TOP_LEVEL_KEYS = {
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


class InvalidDocument(ValueError):
    """The result is not the exact PerformanceResultV1 contract."""


def _record(value, keys, field):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise InvalidDocument(field)
    return value


def _integer(value, minimum, maximum, field):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidDocument(field)
    return value


def _duration(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidDocument(field)
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= MAX_DURATION_MS:
        raise InvalidDocument(field)
    return number


def _summary(value, field):
    if not isinstance(value, dict):
        raise InvalidDocument(field)
    if value.get("state") == "unavailable":
        _record(value, UNAVAILABLE_KEYS, field)
        if value["reason"] not in UNAVAILABLE_REASONS[1:]:
            raise InvalidDocument(field)
        return {"state": "unavailable", "reason": value["reason"]}
    _record(value, SUMMARY_KEYS, field)
    if value["state"] != "available":
        raise InvalidDocument(field)
    count = _integer(value["sampleCount"], 1, MAX_SAMPLES, field)
    median = _duration(value["medianMs"], field)
    p95 = _duration(value["p95Ms"], field)
    maximum = _duration(value["maxMs"], field)
    if not median <= p95 <= maximum:
        raise InvalidDocument(field)
    return {
        "state": "available",
        "sampleCount": count,
        "median": median,
        "p95": p95,
        "max": maximum,
    }


def parse_document(payload: bytes, environment: str, *, now: float | None = None) -> dict:
    """Parse the exact V1 schema without retaining open-ended payload values."""
    if len(payload) > MAX_BYTES:
        raise OverflowError("performance result exceeds 65536 bytes")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise InvalidDocument("JSON") from error
    _record(document, TOP_LEVEL_KEYS, "document")
    if (
        type(document["schemaVersion"]) is not int
        or document["schemaVersion"] != 1
        or document["state"] not in RESULT_STATES
    ):
        raise InvalidDocument("schemaVersion/state")
    measured_at = _integer(document["measuredAt"], 0, 9_007_199_254_740_991, "measuredAt")
    if now is None:
        now = time.time()
    if measured_at > int(now) + MAX_FUTURE_SKEW_SECONDS:
        raise InvalidDocument("measuredAt exceeds the allowed clock skew")

    build = _record(document["build"], {"environment", "tag"}, "build")
    if (
        build["environment"] != environment
        or not isinstance(build["tag"], str)
        or not BUILD_TAG.fullmatch(build["tag"])
    ):
        raise InvalidDocument("build identity")
    runtime = _record(
        document["environment"],
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
    if runtime["browser"] not in ("chromium", "firefox", "webkit"):
        raise InvalidDocument("browser")
    _integer(runtime["browserMajorVersion"], 1, 999, "browserMajorVersion")
    _integer(runtime["viewportWidth"], 1, 10_000, "viewportWidth")
    _integer(runtime["viewportHeight"], 1, 10_000, "viewportHeight")
    if (
        runtime["renderingMode"] not in ("immersive", "fallback")
        or runtime["rendererClass"] not in RENDERER_CLASSES
        or runtime["frameMeasurementProfile"] not in ("controlled_hardware_v1", "unsupported")
    ):
        raise InvalidDocument("renderer environment")

    conditions = _record(
        document["conditions"],
        {"warmupMs", "interactionName", "requestedActions", "eventsPerAction", "requestedSamples"},
        "conditions",
    )
    _duration(conditions["warmupMs"], "warmupMs")
    actions = _integer(conditions["requestedActions"], 1, MAX_SAMPLES, "requestedActions")
    samples = _integer(conditions["requestedSamples"], 1, MAX_SAMPLES, "requestedSamples")
    if (
        conditions["interactionName"] != "keyboard_movement"
        or conditions["eventsPerAction"] != EVENTS_PER_ACTION
        or samples != actions * EVENTS_PER_ACTION
    ):
        raise InvalidDocument("controlled interaction")

    renderer = _record(document["renderer"], {"state", "fallbackReason"}, "renderer")
    if (
        renderer["state"] not in RENDERER_STATES
        or renderer["fallbackReason"] not in FALLBACK_STATUSES
    ):
        raise InvalidDocument("renderer")
    invalid_renderer = (
        (
            renderer["state"] == "immersive"
            and (runtime["renderingMode"] != "immersive" or renderer["fallbackReason"] != "none")
        )
        or (
            renderer["state"] == "fallback"
            and (runtime["renderingMode"] != "fallback" or renderer["fallbackReason"] == "none")
        )
        or (renderer["state"] == "unavailable" and renderer["fallbackReason"] == "none")
    )
    if invalid_renderer:
        raise InvalidDocument("renderer relationship")

    ready = _summary(document["applicationReady"], "applicationReady")
    interaction = _summary(document["interactionLatency"], "interactionLatency")
    frame = _summary(document["frameTime"], "frameTime")
    unavailable = ready["state"] == "unavailable" or interaction["state"] == "unavailable"
    if (document["state"] == "unavailable") != unavailable:
        raise InvalidDocument("result state relationship")
    if interaction["state"] == "available" and interaction["sampleCount"] != samples:
        raise InvalidDocument("interaction samples")
    frame_supported = (
        runtime["browser"] == "chromium"
        and runtime["renderingMode"] == "immersive"
        and runtime["rendererClass"] == "hardware"
        and runtime["frameMeasurementProfile"] == "controlled_hardware_v1"
        and renderer == {"state": "immersive", "fallbackReason": "none"}
    )
    if runtime["frameMeasurementProfile"] == "controlled_hardware_v1" and not frame_supported:
        raise InvalidDocument("frame profile")
    if frame["state"] == "available" and (not frame_supported or frame["sampleCount"] != 120):
        raise InvalidDocument("frame samples")
    return {
        "state": document["state"],
        "measured_at": document["measuredAt"],
        "renderer_class": runtime["rendererClass"],
        "renderer_state": renderer["state"],
        "fallback": renderer["fallbackReason"],
        "ready": ready,
        "interaction": interaction,
        "frame": frame,
    }


def render(
    payload: bytes | None, environment: str, status="valid", *, now: float | None = None
) -> str:
    values = parse_document(payload, environment, now=now) if payload is not None else None
    state = values["state"] if values else "unavailable"
    lines = [
        "# HELP daniel_performance_collection_up Whether the passive result was "
        "collected and validated.",
        "# TYPE daniel_performance_collection_up gauge",
        f'daniel_performance_collection_up{{environment="{environment}"}} '
        f"{int(values is not None)}",
    ]
    for metric, domain, selected, label in (
        ("daniel_performance_document_status", DOCUMENT_STATUSES, status, "status"),
        ("daniel_performance_result_state", RESULT_STATES, state, "state"),
    ):
        lines.extend(
            f'{metric}{{environment="{environment}",{label}="{item}"}} {int(item == selected)}'
            for item in domain
        )
    if values:
        lines.extend(
            (
                "# HELP daniel_performance_measurement_timestamp_seconds Unix time of the "
                "controlled measurement.",
                "# TYPE daniel_performance_measurement_timestamp_seconds gauge",
                f'daniel_performance_measurement_timestamp_seconds{{environment="{environment}"}} '
                f'{values["measured_at"]}',
            )
        )
        for metric, domain, selected, label in (
            (
                "daniel_performance_renderer_class",
                RENDERER_CLASSES,
                values["renderer_class"],
                "renderer_class",
            ),
            (
                "daniel_performance_renderer_state",
                RENDERER_STATES,
                values["renderer_state"],
                "renderer_state",
            ),
            (
                "daniel_performance_fallback_status",
                FALLBACK_STATUSES,
                values["fallback"],
                "fallback_status",
            ),
        ):
            lines.extend(
                f'{metric}{{environment="{environment}",{label}="{item}"}} {int(item == selected)}'
                for item in domain
            )
        summaries = {
            "application_ready": values["ready"],
            "interaction_latency": values["interaction"],
            "frame_time": values["frame"],
        }
        for name in MEASUREMENTS:
            summary = summaries[name]
            reason = summary.get("reason", "none")
            lines.extend(
                f'daniel_performance_measurement_status{{environment="{environment}",'
                f'measurement="{name}",reason="{item}"}} {int(item == reason)}'
                for item in UNAVAILABLE_REASONS
            )
            if summary["state"] == "available":
                lines.extend(
                    f'daniel_performance_{name}_seconds{{environment="{environment}",'
                    f'renderer_class="{values["renderer_class"]}",'
                    f'renderer_state="{values["renderer_state"]}",'
                    f'fallback_status="{values["fallback"]}",'
                    f'statistic="{statistic}"}} {summary[statistic] / 1000:g}'
                    for statistic in ("median", "p95", "max")
                )
    return "\n".join(lines) + "\n"


def collect(path: Path | None, environment: str, *, now: float | None = None) -> str:
    try:
        if path is None:
            return render(None, environment, "unavailable", now=now)
        with path.open("rb") as stream:
            payload = stream.read(MAX_BYTES + 1)
        return render(payload, environment, now=now)
    except OverflowError:
        return render(None, environment, "oversized", now=now)
    except InvalidDocument:
        return render(None, environment, "malformed", now=now)
    except OSError:
        return render(None, environment, "unavailable", now=now)


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
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--environment", choices=("staging", "prod"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    write_textfile(args.output, collect(args.result, args.environment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
