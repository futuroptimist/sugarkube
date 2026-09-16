#!/usr/bin/env python3
"""Validate the application-owned visitor result and render bounded metrics.

This integration does not run browser assertions. It accepts only the exact,
sanitary aggregate emitted by danielsmith.io and keeps optional rendering separate.
"""

from __future__ import annotations

import math
import re
import time

FAILURE_STAGES = {
    "homepage_delivery",
    "javascript_initialization",
    "essential_assets",
    "accessible_fallback",
    "resume_pdf",
    "timeout",
    "producer_interrupted",
}
OPTIONAL_RENDERER_STATES = {"available", "unavailable", "disabled", "unknown"}
RESULT_FIELDS = {"state", "freshness", "aggregateDurationMs", "failureStage"}
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_CLOCK_SKEW_SECONDS = 300


def validate_result(value: dict, now: float | None = None) -> dict:
    """Return an exact sanitized application result or reject it fail closed."""
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ValueError("result does not match the exact sanitized schema")
    if value["state"] not in {"success", "failure"}:
        raise ValueError("result state is invalid")
    freshness = value["freshness"]
    duration = value["aggregateDurationMs"]
    if type(freshness) is not int or freshness < 0:
        raise ValueError("result freshness is invalid")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("result aggregate duration is invalid")
    current = time.time() if now is None else now
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or not math.isfinite(current)
    ):
        raise ValueError("current time is invalid")
    if freshness > current + MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("result freshness is too far in the future")
    stage = value["failureStage"]
    if value["state"] == "success":
        if stage is not None:
            raise ValueError("successful result cannot have a failure stage")
    elif not isinstance(stage, str) or stage not in FAILURE_STAGES:
        raise ValueError("failed result must have a bounded failure stage")
    return dict(value)


def _duration(value: object, field: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*[smh]", value):
        raise ValueError(f"producer {field} is invalid")
    return int(value[:-1]) * {"s": 1, "m": 60, "h": 3600}[value[-1]]


def _validate_producer(producer: dict) -> None:
    for field in ("name", "application", "environment"):
        if not isinstance(producer.get(field), str) or not IDENTITY.fullmatch(producer[field]):
            raise ValueError("producer identity is invalid")
    if type(producer.get("enabled")) is not bool:
        raise ValueError("producer enabled state is invalid")


def render_metrics(
    producer: dict,
    result: dict | None = None,
    *,
    previous_result: dict | None = None,
    optional_renderer_state: str | None = None,
    now: float | None = None,
) -> str:
    """Render disabled/unavailable/stale/failure/recovery/success without fake success."""
    _validate_producer(producer)
    current = time.time() if now is None else now
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or not math.isfinite(current)
    ):
        raise ValueError("current time is invalid")
    cadence = _duration(producer.get("cadence"), "cadence")
    timeout = _duration(producer.get("timeout"), "timeout")
    if not producer["enabled"] and any(
        x is not None for x in (result, previous_result, optional_renderer_state)
    ):
        raise ValueError("disabled producer cannot supply runtime evidence")
    if (
        optional_renderer_state is not None
        and optional_renderer_state not in OPTIONAL_RENDERER_STATES
    ):
        raise ValueError("optional renderer state is invalid")
    labels = (
        f'application="{producer["application"]}",environment="{producer["environment"]}",'
        f'producer="{producer["name"]}"'
    )
    lifecycle = "disabled" if not producer["enabled"] else "unavailable"
    lines = [
        "# HELP danielsmith_visitor_journey_monitoring_enabled Whether the journey is authorized.",
        "# TYPE danielsmith_visitor_journey_monitoring_enabled gauge",
        f"danielsmith_visitor_journey_monitoring_enabled{{{labels}}} {int(producer['enabled'])}",
    ]
    if result is not None:
        result = validate_result(result, current)
        previous = (
            validate_result(previous_result, current) if previous_result is not None else None
        )
        if current - result["freshness"] > cadence + timeout:
            lifecycle = "stale"
        elif result["state"] == "failure":
            lifecycle = "failed"
        elif previous is not None and previous["state"] == "failure":
            lifecycle = "recovered"
        else:
            lifecycle = "successful"
        stage = result["failureStage"] or "none"
        lines += [
            "# HELP danielsmith_visitor_journey_success Last essential journey result.",
            "# TYPE danielsmith_visitor_journey_success gauge",
            f"danielsmith_visitor_journey_success{{{labels}}} {int(result['state'] == 'success')}",
            "# HELP danielsmith_visitor_journey_freshness_timestamp_seconds "
            "Completion time in Unix seconds.",
            "# TYPE danielsmith_visitor_journey_freshness_timestamp_seconds gauge",
            "danielsmith_visitor_journey_freshness_timestamp_seconds"
            f"{{{labels}}} {result['freshness']}",
            "# HELP danielsmith_visitor_journey_duration_seconds "
            "Aggregate essential journey duration.",
            "# TYPE danielsmith_visitor_journey_duration_seconds gauge",
            "danielsmith_visitor_journey_duration_seconds"
            f"{{{labels}}} {result['aggregateDurationMs'] / 1000:g}",
            "# HELP danielsmith_visitor_journey_failure_stage "
            "Last bounded essential failure stage.",
            "# TYPE danielsmith_visitor_journey_failure_stage gauge",
            f'danielsmith_visitor_journey_failure_stage{{{labels},failure_stage="{stage}"}} 1',
        ]
    renderer = "disabled" if not producer["enabled"] else (optional_renderer_state or "unknown")
    lines += [
        "# HELP danielsmith_visitor_journey_lifecycle_state Current essential journey lifecycle.",
        "# TYPE danielsmith_visitor_journey_lifecycle_state gauge",
        f'danielsmith_visitor_journey_lifecycle_state{{{labels},state="{lifecycle}"}} 1',
        "# HELP danielsmith_optional_renderer_state Separately reported optional renderer state.",
        "# TYPE danielsmith_optional_renderer_state gauge",
        f'danielsmith_optional_renderer_state{{{labels},state="{renderer}"}} 1',
    ]
    return "\n".join(lines) + "\n"
