#!/usr/bin/env python3
"""Validate the application-owned visitor result and render bounded metrics."""

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
RESULT_FIELDS = {"state", "freshness", "aggregateDurationMs", "failureStage"}
IDENTITY = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_CLOCK_SKEW_SECONDS = 300


def _duration(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*[smh]", value):
        raise ValueError("producer cadence or timeout is invalid")
    return int(value[:-1]) * {"s": 1, "m": 60, "h": 3600}[value[-1]]


def validate_result(value: dict, now: float | None = None) -> dict:
    """Accept only the exact sanitized contract from danielsmith.io PR #1092."""
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ValueError("result does not match the exact sanitized schema")
    current = time.time() if now is None else now
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or not math.isfinite(current)
    ):
        raise ValueError("current time is invalid")
    if value["state"] not in {"success", "failure"}:
        raise ValueError("result state is invalid")
    freshness = value["freshness"]
    if type(freshness) is not int or freshness < 0 or freshness > current + MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("result freshness is invalid")
    duration = value["aggregateDurationMs"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("result duration is invalid")
    stage = value["failureStage"]
    if value["state"] == "success":
        if stage is not None:
            raise ValueError("successful result has a failure stage")
    elif stage not in FAILURE_STAGES:
        raise ValueError("failed result has an invalid failure stage")
    return dict(value)


def render_metrics(
    producer: dict,
    result: dict | None = None,
    *,
    now: float | None = None,
    previous_state: str | None = None,
) -> str:
    """Render disabled, unavailable, stale, failure, recovery, and success distinctly."""
    if not isinstance(producer, dict):
        raise ValueError("producer metadata is invalid")
    for field in ("name", "application", "environment"):
        if not isinstance(producer.get(field), str) or not IDENTITY.fullmatch(producer[field]):
            raise ValueError("producer identity is invalid")
    if type(producer.get("enabled")) is not bool:
        raise ValueError("producer enabled state is invalid")
    current = time.time() if now is None else now
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or not math.isfinite(current)
    ):
        raise ValueError("current time is invalid")
    cadence, timeout = _duration(producer.get("cadence")), _duration(producer.get("timeout"))
    if timeout >= cadence:
        raise ValueError("producer timeout must be shorter than cadence")
    if not producer["enabled"] and result is not None:
        raise ValueError("disabled producer cannot supply a result")
    if previous_state not in {None, "unavailable", "stale", "failure", "success", "recovered"}:
        raise ValueError("previous state is invalid")
    labels = ",".join(f'{key}="{producer[key]}"' for key in ("application", "environment", "name"))
    lifecycle = "disabled" if not producer["enabled"] else "unavailable"
    lines = [
        "# HELP danielsmith_visitor_journey_monitoring_enabled Whether execution is authorized.",
        "# TYPE danielsmith_visitor_journey_monitoring_enabled gauge",
        f"danielsmith_visitor_journey_monitoring_enabled{{{labels}}} {int(producer['enabled'])}",
    ]
    if result is not None:
        result = validate_result(result, current)
        success = int(result["state"] == "success")
        if current - result["freshness"] > cadence + timeout:
            lifecycle = "stale"
        elif not success:
            lifecycle = "failure"
        elif previous_state in {"unavailable", "stale", "failure"}:
            lifecycle = "recovered"
        else:
            lifecycle = "success"
        stage = result["failureStage"] or "none"
        lines += [
            "# HELP danielsmith_visitor_journey_success Last essential journey result.",
            "# TYPE danielsmith_visitor_journey_success gauge",
            f"danielsmith_visitor_journey_success{{{labels}}} {success}",
            "# HELP danielsmith_visitor_journey_freshness_timestamp_seconds "
            "Unix completion time.",
            "# TYPE danielsmith_visitor_journey_freshness_timestamp_seconds gauge",
            "danielsmith_visitor_journey_freshness_timestamp_seconds"
            f"{{{labels}}} {result['freshness']}",
            "# HELP danielsmith_visitor_journey_duration_seconds "
            "Aggregate essential journey duration.",
            "# TYPE danielsmith_visitor_journey_duration_seconds gauge",
            "danielsmith_visitor_journey_duration_seconds"
            f"{{{labels}}} {result['aggregateDurationMs'] / 1000:g}",
            "# HELP danielsmith_visitor_journey_failure_stage Last bounded essential failure stage.",
            "# TYPE danielsmith_visitor_journey_failure_stage gauge",
            f'danielsmith_visitor_journey_failure_stage{{{labels},failure_stage="{stage}"}} 1',
        ]
    lines += [
        "# HELP danielsmith_visitor_journey_state Current bounded producer and journey state.",
        "# TYPE danielsmith_visitor_journey_state gauge",
        f'danielsmith_visitor_journey_state{{{labels},state="{lifecycle}"}} 1',
    ]
    return "\n".join(lines) + "\n"
