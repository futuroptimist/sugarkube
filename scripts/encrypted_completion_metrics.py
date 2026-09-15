#!/usr/bin/env python3
"""Render a bounded encrypted-completion result as payload-free Prometheus metrics."""

import json
import math
import re
from pathlib import Path

RESULT_FIELDS = {
    "schemaVersion",
    "application",
    "environment",
    "attemptedAt",
    "durationSeconds",
    "outcome",
    "failureStage",
    "clientDecrypted",
    "responseValid",
}
FAILURE_STAGES = {
    "timeout",
    "compute_unavailable",
    "malformed_completion",
    "interrupted",
    "decryption_failed",
}


def render_metrics(result: dict, *, last_success: int | None = None) -> str:
    """Validate the exact evidence schema and return only bounded telemetry."""
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise ValueError("result does not match the exact bounded schema")
    if result["schemaVersion"] != 1 or result["environment"] not in {"staging", "prod"}:
        raise ValueError("result contract version or environment is invalid")
    if not isinstance(result["application"], str) or not re.fullmatch(
        r"[a-z][a-z0-9-]*", result["application"]
    ):
        raise ValueError("result application is invalid")
    if type(result["attemptedAt"]) is not int or result["attemptedAt"] < 1:
        raise ValueError("result timestamp is invalid")
    duration = result["durationSeconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError("result duration is invalid")
    if type(result["clientDecrypted"]) is not bool or type(result["responseValid"]) is not bool:
        raise ValueError("result verification flags are invalid")
    success = result["outcome"] == "success"
    expected_stage = "none" if success else result["failureStage"]
    if (
        result["outcome"] not in {"success", "failure"}
        or (
            success
            and (
                expected_stage != "none"
                or not result["clientDecrypted"]
                or not result["responseValid"]
            )
        )
        or (not success and expected_stage not in FAILURE_STAGES)
    ):
        raise ValueError("result outcome is inconsistent")
    if not success and (result["clientDecrypted"] or result["responseValid"]):
        raise ValueError("failed result cannot claim completion verification")
    if last_success is not None and (type(last_success) is not int or last_success < 1):
        raise ValueError("last successful completion timestamp is invalid")
    successful_at = result["attemptedAt"] if success else (last_success or 0)
    labels = f'application="{result["application"]}",environment="{result["environment"]}"'
    stage_labels = labels + f',stage="{expected_stage}"'
    return (
        "# TYPE encrypted_completion_monitoring_enabled gauge\n"
        f"encrypted_completion_monitoring_enabled{{{labels}}} 1\n"
        "# TYPE encrypted_completion_success gauge\n"
        f"encrypted_completion_success{{{labels}}} {int(success)}\n"
        "# TYPE encrypted_completion_last_attempt_timestamp_seconds gauge\n"
        f"encrypted_completion_last_attempt_timestamp_seconds{{{labels}}} {result['attemptedAt']}\n"
        "# TYPE encrypted_completion_last_success_timestamp_seconds gauge\n"
        f"encrypted_completion_last_success_timestamp_seconds{{{labels}}} {successful_at}\n"
        "# TYPE encrypted_completion_duration_seconds gauge\n"
        f"encrypted_completion_duration_seconds{{{labels}}} {duration}\n"
        "# TYPE encrypted_completion_failure_stage gauge\n"
        f"encrypted_completion_failure_stage{{{stage_labels}}} {int(not success)}\n"
    )


def load_and_render(path: Path, *, last_success: int | None = None) -> str:
    return render_metrics(json.loads(path.read_text(encoding="utf-8")), last_success=last_success)
