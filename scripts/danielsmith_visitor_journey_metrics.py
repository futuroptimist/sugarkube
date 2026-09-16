#!/usr/bin/env python3
"""Validate application-owned visitor-journey results and render bounded metrics."""

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
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_result(value: dict) -> dict:
    """Accept only the exact sanitized contract from danielsmith.io PR 1092."""
    if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
        raise ValueError("result does not match the exact sanitized schema")
    if value["state"] not in {"success", "failure"}:
        raise ValueError("result state is invalid")
    for field in ("freshness", "aggregateDurationMs"):
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ValueError(f"result {field} is invalid")
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"result {field} is invalid")
    stage = value["failureStage"]
    if stage is not None and stage not in FAILURE_STAGES:
        raise ValueError("result failureStage is invalid")
    if (value["state"] == "success") != (stage is None):
        raise ValueError("result state and failureStage contradict")
    return dict(value)


def _seconds(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*[smh]", value):
        raise ValueError("producer cadence is invalid")
    return int(value[:-1]) * {"s": 1, "m": 60, "h": 3600}[value[-1]]


def _producer(producer: dict) -> None:
    if not isinstance(producer, dict):
        raise ValueError("producer metadata is invalid")
    for field in ("name", "application", "environment"):
        if not isinstance(producer.get(field), str) or not IDENTITY.fullmatch(producer[field]):
            raise ValueError("producer identity is invalid")
    if type(producer.get("enabled")) is not bool:
        raise ValueError("producer enabled state is invalid")
    _seconds(producer.get("cadence"))
    _seconds(producer.get("timeout"))


def render_metrics(
    producer: dict,
    result: dict | None = None,
    *,
    now: float | None = None,
    previous_state: str | None = None,
) -> str:
    """Render disabled/unavailable/stale/failed/recovered/successful distinctly."""
    _producer(producer)
    current = time.time() if now is None else now
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or not math.isfinite(current)
    ):
        raise ValueError("current time is invalid")
    if not producer["enabled"] and result is not None:
        raise ValueError("disabled producer cannot supply a result")
    if previous_state not in {None, "failure", "success"}:
        raise ValueError("previous state is invalid")
    labels = (
        f'application="{producer["application"]}",environment="{producer["environment"]}",'
        f'producer="{producer["name"]}"'
    )
    lifecycle = "disabled" if not producer["enabled"] else "unavailable"
    lines = [
        "# HELP danielsmith_visitor_journey_monitoring_enabled "
        "Whether this reviewed producer is enabled.",
        "# TYPE danielsmith_visitor_journey_monitoring_enabled gauge",
        f"danielsmith_visitor_journey_monitoring_enabled{{{labels}}} {int(producer['enabled'])}",
    ]
    if result is not None:
        result = validate_result(result)
        age = current - result["freshness"]
        if age > _seconds(producer["cadence"]) + _seconds(producer["timeout"]):
            lifecycle = "stale"
        elif result["state"] == "failure":
            lifecycle = "failed"
        elif previous_state == "failure":
            lifecycle = "recovered"
        else:
            lifecycle = "successful"
        stage = result["failureStage"] or "none"
        lines += [
            "# HELP danielsmith_visitor_journey_success Last essential journey result.",
            "# TYPE danielsmith_visitor_journey_success gauge",
            f"danielsmith_visitor_journey_success{{{labels}}} {int(result['state'] == 'success')}",
            "# HELP danielsmith_visitor_journey_timestamp_seconds Unix completion time.",
            "# TYPE danielsmith_visitor_journey_timestamp_seconds gauge",
            f"danielsmith_visitor_journey_timestamp_seconds{{{labels}}} {result['freshness']}",
            "# HELP danielsmith_visitor_journey_duration_seconds Aggregate journey duration.",
            "# TYPE danielsmith_visitor_journey_duration_seconds gauge",
            "danielsmith_visitor_journey_duration_seconds"
            f"{{{labels}}} {result['aggregateDurationMs'] / 1000}",
            "# HELP danielsmith_visitor_journey_failure_stage Last bounded failure stage.",
            "# TYPE danielsmith_visitor_journey_failure_stage gauge",
            f'danielsmith_visitor_journey_failure_stage{{{labels},failure_stage="{stage}"}} 1',
        ]
    lines += [
        "# HELP danielsmith_visitor_journey_lifecycle_state Current bounded producer lifecycle.",
        "# TYPE danielsmith_visitor_journey_lifecycle_state gauge",
        f'danielsmith_visitor_journey_lifecycle_state{{{labels},state="{lifecycle}"}} 1',
    ]
    return "\n".join(lines) + "\n"
