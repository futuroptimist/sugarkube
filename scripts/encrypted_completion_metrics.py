#!/usr/bin/env python3
"""Render bounded encrypted-completion evidence as privacy-safe Prometheus metrics.

This module deliberately does not make requests or perform decryption. Application-owned
clients may provide a result only after completing and validating their real E2EE journey.
"""

from __future__ import annotations

import time

FAILURE_STAGES = {
    "none",
    "timeout",
    "compute_unavailable",
    "malformed_completion",
    "decryption_failed",
    "interrupted",
}
RESULT_KEYS = {
    "schemaVersion",
    "completedAt",
    "durationSeconds",
    "failureStage",
    "decrypted",
    "valid",
}


def render_metrics(producer: dict, result: dict | None, *, now: int | None = None) -> str:
    """Validate one result and return metrics containing only bounded labels and numbers."""
    labels = f'application="{producer["application"]}",' f'environment="{producer["environment"]}"'
    enabled = producer.get("enabled") is True
    lines = [f"encrypted_completion_monitoring_enabled{{{labels}}} {int(enabled)}"]
    if not enabled:
        if result is not None:
            raise ValueError("disabled producer cannot publish an execution result")
        return "\n".join(lines) + "\n"
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        raise ValueError("result does not match the exact bounded schema")
    stage = result["failureStage"]
    completed = result["completedAt"]
    duration = result["durationSeconds"]
    if result["schemaVersion"] != 1 or stage not in FAILURE_STAGES:
        raise ValueError("result has an invalid schema or failure stage")
    if (
        type(completed) is not int
        or completed < 1
        or type(duration) not in {int, float}
        or duration < 0
    ):
        raise ValueError("result timestamp or duration is invalid")
    if type(result["decrypted"]) is not bool or type(result["valid"]) is not bool:
        raise ValueError("result completion flags are invalid")
    current = int(time.time()) if now is None else now
    if completed > current + 60:
        raise ValueError("result timestamp exceeds allowed clock skew")
    success = stage == "none" and result["decrypted"] and result["valid"]
    if stage == "none" and not success:
        raise ValueError("successful stage requires decrypted and valid completion")
    if stage != "none" and (result["decrypted"] or result["valid"]):
        raise ValueError("failed result cannot claim decrypted or valid completion")
    lines.extend(
        [
            f"encrypted_completion_success{{{labels}}} {int(success)}",
            f"encrypted_completion_attempt_timestamp_seconds{{{labels}}} {completed}",
            f"encrypted_completion_duration_seconds{{{labels}}} {duration}",
            f'encrypted_completion_failure_stage{{{labels},stage="{stage}"}} 1',
        ]
    )
    if success:
        lines.append(f"encrypted_completion_last_success_timestamp_seconds{{{labels}}} {completed}")
    return "\n".join(lines) + "\n"
