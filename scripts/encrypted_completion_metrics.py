#!/usr/bin/env python3
"""Validate sanitized client-completion evidence and render metric text.

This module never performs a request or decrypts application data. Application-owned
clients may supply only the bounded assertions defined here after doing that work.
"""

from __future__ import annotations

import math

FAILURE_STAGES = {
    "none",
    "timeout",
    "compute_unavailable",
    "malformed_completion",
    "interrupted",
}
EVIDENCE_FIELDS = {
    "schemaVersion",
    "producer",
    "application",
    "environment",
    "outcome",
    "failureStage",
    "attemptedAt",
    "completedAt",
    "durationSeconds",
    "clientDecryptionVerified",
    "responseValid",
}


def validate_evidence(value: dict) -> dict:
    """Return an exact sanitized evidence record or reject it fail closed."""
    if not isinstance(value, dict) or set(value) != EVIDENCE_FIELDS:
        raise ValueError("evidence does not match the exact sanitized schema")
    if value["schemaVersion"] != 1 or value["outcome"] not in {"success", "failure"}:
        raise ValueError("evidence schema or outcome is invalid")
    if value["failureStage"] not in FAILURE_STAGES:
        raise ValueError("evidence failure stage is invalid")
    for field in ("producer", "application", "environment"):
        if not isinstance(value[field], str) or not value[field]:
            raise ValueError(f"evidence {field} is invalid")
    for field in ("attemptedAt", "completedAt"):
        if type(value[field]) is not int or value[field] < 1:
            raise ValueError(f"evidence {field} is invalid")
    duration = value["durationSeconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("evidence duration is invalid")
    if (
        type(value["clientDecryptionVerified"]) is not bool
        or type(value["responseValid"]) is not bool
    ):
        raise ValueError("evidence assertions are invalid")
    succeeded = value["outcome"] == "success"
    if succeeded != (value["failureStage"] == "none"):
        raise ValueError("outcome and failure stage contradict")
    if succeeded != (value["clientDecryptionVerified"] and value["responseValid"]):
        raise ValueError("success requires client decryption and response validity")
    if value["completedAt"] < value["attemptedAt"]:
        raise ValueError("completion predates attempt")
    return dict(value)


def render_metrics(producer: dict, evidence: dict | None = None) -> str:
    """Render state metrics; a disabled producer is distinct from absent/stale data."""
    labels = (
        f'application="{producer["application"]}",environment="{producer["environment"]}",'
        f'producer="{producer["name"]}"'
    )
    enabled = int(producer["enabled"])
    lines = [
        "# HELP encrypted_completion_monitoring_enabled "
        "Whether the declared producer is intentionally enabled.",
        "# TYPE encrypted_completion_monitoring_enabled gauge",
        f"encrypted_completion_monitoring_enabled{{{labels}}} {enabled}",
    ]
    if evidence is not None:
        evidence = validate_evidence(evidence)
        if any(
            evidence[key] != producer[source]
            for key, source in (
                ("producer", "name"),
                ("application", "application"),
                ("environment", "environment"),
            )
        ):
            raise ValueError("evidence identity contradicts producer")
        success = int(evidence["outcome"] == "success")
        stage_labels = f'{labels},failure_stage="{evidence["failureStage"]}"'
        lines.extend(
            [
                "# HELP encrypted_completion_success "
                "Last client-side decryption and validity result.",
                "# TYPE encrypted_completion_success gauge",
                f"encrypted_completion_success{{{labels}}} {success}",
                "# HELP encrypted_completion_attempt_timestamp_seconds "
                "Unix time of the last attempt.",
                "# TYPE encrypted_completion_attempt_timestamp_seconds gauge",
                "encrypted_completion_attempt_timestamp_seconds"
                f'{{{labels}}} {evidence["attemptedAt"]}',
                "# HELP encrypted_completion_last_success_timestamp_seconds "
                "Unix time of the last successful completion.",
                "# TYPE encrypted_completion_last_success_timestamp_seconds gauge",
                "encrypted_completion_last_success_timestamp_seconds"
                f'{{{labels}}} {evidence["completedAt"] if success else 0}',
                "# HELP encrypted_completion_duration_seconds "
                "End-to-end client completion duration, not HTTP polling latency.",
                "# TYPE encrypted_completion_duration_seconds gauge",
                "encrypted_completion_duration_seconds"
                f'{{{labels}}} {evidence["durationSeconds"]}',
                "# HELP encrypted_completion_failure_stage Last bounded completion failure stage.",
                "# TYPE encrypted_completion_failure_stage gauge",
                f"encrypted_completion_failure_stage{{{stage_labels}}} 1",
            ]
        )
    return "\n".join(lines) + "\n"
