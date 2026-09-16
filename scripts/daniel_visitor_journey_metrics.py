#!/usr/bin/env python3
"""Validate the application-owned visitor-journey aggregate and render metrics.

This adapter does not run browser assertions.  It accepts only the four-field,
sanitized result produced by danielsmith.io and static repository identities.
"""

from __future__ import annotations

import math
import re

FAILURE_STAGES = {
    "homepage_delivery",
    "javascript_initialization",
    "essential_assets",
    "accessible_fallback",
    "resume_pdf",
    "timeout",
    "producer_interrupted",
}
RESULT_FIELDS = {"state", "freshness", "aggregateDurationMs", "failureStage"}
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_CLOCK_SKEW_SECONDS = 300


def _duration_seconds(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*[smh]", value):
        raise ValueError("producer duration is invalid")
    return int(value[:-1]) * {"s": 1, "m": 60, "h": 3600}[value[-1]]


def validate_result(value: dict, now: float) -> dict:
    """Return an exact, bounded application result or reject it fail closed."""
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ValueError("result does not match the exact sanitized schema")
    if value["state"] not in {"success", "failure"}:
        raise ValueError("result state is invalid")
    freshness = value["freshness"]
    duration = value["aggregateDurationMs"]
    if (
        isinstance(freshness, bool)
        or not isinstance(freshness, (int, float))
        or not math.isfinite(freshness)
        or freshness < 0
        or freshness > now + MAX_CLOCK_SKEW_SECONDS
    ):
        raise ValueError("result freshness is invalid")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("result duration is invalid")
    stage = value["failureStage"]
    if value["state"] == "success" and stage is not None:
        raise ValueError("successful result has a failure stage")
    if value["state"] == "failure" and stage not in FAILURE_STAGES:
        raise ValueError("failed result has an invalid failure stage")
    return dict(value)


def _validate_producer(producer: dict) -> None:
    for field in ("name", "application", "environment"):
        if not isinstance(producer.get(field), str) or not IDENTITY.fullmatch(producer[field]):
            raise ValueError("producer identity is invalid")
    if type(producer.get("enabled")) is not bool:
        raise ValueError("producer enabled state is invalid")
    if type(producer.get("optionalRendererEnabled")) is not bool:
        raise ValueError("optional renderer enabled state is invalid")


def render_metrics(
    producer: dict,
    result: dict | None = None,
    *,
    now: float,
    previous_failed: bool = False,
    optional_renderer_state: str | None = None,
) -> str:
    """Render bounded metrics without converting disabled or absent data to success."""
    _validate_producer(producer)
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError("current time is invalid")
    if not producer["enabled"] and result is not None:
        raise ValueError("disabled producer cannot supply a result")
    if not producer["enabled"]:
        lifecycle = "disabled"
    elif result is None:
        lifecycle = "unavailable"
    else:
        result = validate_result(result, now)
        stale_after = _duration_seconds(producer["cadence"]) + _duration_seconds(
            producer["timeout"]
        )
        if now - result["freshness"] > stale_after:
            lifecycle = "stale"
        elif result["state"] == "failure":
            lifecycle = "failed"
        elif previous_failed:
            lifecycle = "recovered"
        else:
            lifecycle = "successful"

    if not producer["optionalRendererEnabled"]:
        if optional_renderer_state is not None:
            raise ValueError("disabled optional renderer cannot supply state")
        renderer = "disabled"
    else:
        renderer = optional_renderer_state or "unavailable"
        if renderer not in {"unavailable", "success", "failure"}:
            raise ValueError("optional renderer state is invalid")

    labels = (
        f'application="{producer["application"]}",environment="{producer["environment"]}",'
        f'producer="{producer["name"]}"'
    )
    lines = [
        "# HELP daniel_visitor_journey_monitoring_enabled Whether scheduling is authorized.",
        "# TYPE daniel_visitor_journey_monitoring_enabled gauge",
        f"daniel_visitor_journey_monitoring_enabled{{{labels}}} {int(producer['enabled'])}",
        "# HELP daniel_visitor_journey_lifecycle_state Current bounded lifecycle state.",
        "# TYPE daniel_visitor_journey_lifecycle_state gauge",
        f'daniel_visitor_journey_lifecycle_state{{{labels},state="{lifecycle}"}} 1',
        "# HELP daniel_visitor_journey_optional_renderer_state "
        "Separately owned optional renderer state.",
        "# TYPE daniel_visitor_journey_optional_renderer_state gauge",
        f'daniel_visitor_journey_optional_renderer_state{{{labels},state="{renderer}"}} 1',
    ]
    if result is not None:
        success = int(result["state"] == "success")
        lines += [
            "# HELP daniel_visitor_journey_success Last essential journey result.",
            "# TYPE daniel_visitor_journey_success gauge",
            f"daniel_visitor_journey_success{{{labels}}} {success}",
            "# HELP daniel_visitor_journey_freshness_timestamp_seconds "
            "Result completion Unix time.",
            "# TYPE daniel_visitor_journey_freshness_timestamp_seconds gauge",
            f"daniel_visitor_journey_freshness_timestamp_seconds{{{labels}}} {result['freshness']}",
            "# HELP daniel_visitor_journey_duration_seconds Aggregate essential journey duration.",
            "# TYPE daniel_visitor_journey_duration_seconds gauge",
            f"daniel_visitor_journey_duration_seconds{{{labels}}} "
            f"{result['aggregateDurationMs'] / 1000}",
        ]
        if result["failureStage"] is not None:
            lines += [
                "# HELP daniel_visitor_journey_failure_stage Last bounded failure stage.",
                "# TYPE daniel_visitor_journey_failure_stage gauge",
                "daniel_visitor_journey_failure_stage"
                f'{{{labels},failure_stage="{result["failureStage"]}"}} 1',
            ]
    return "\n".join(lines) + "\n"
