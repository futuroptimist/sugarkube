#!/usr/bin/env python3
"""Validate and render sanitized encrypted-completion observability evidence."""

from __future__ import annotations

import json
from pathlib import Path

FAILURE_STAGES = (
    "none",
    "timeout",
    "compute_unavailable",
    "malformed_completion",
    "interrupted",
    "decryption_failed",
)
EVIDENCE_FIELDS = {
    "schemaVersion",
    "application",
    "environment",
    "attemptedAt",
    "durationSeconds",
    "completionValid",
    "decryptionSucceeded",
    "failureStage",
}


class ContractError(ValueError):
    """A privacy-safe contract error."""


def load_contract(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schemaVersion",
        "application",
        "environment",
        "enabled",
        "cadence",
        "timeout",
        "concurrency",
        "quota",
        "route",
        "method",
        "bucket",
        "exemptions",
        "failureStages",
    }
    if not isinstance(value, dict) or set(value) != required or value["schemaVersion"] != 1:
        raise ContractError("producer descriptor has missing or unknown metadata")
    if value["failureStages"] != list(FAILURE_STAGES):
        raise ContractError("producer descriptor has an unsupported failure-stage vocabulary")
    return value


def parse_evidence(value: dict, contract: dict) -> dict:
    """Accept bounded booleans/timings only; request material is structurally impossible."""
    if not isinstance(value, dict) or set(value) != EVIDENCE_FIELDS or value["schemaVersion"] != 1:
        raise ContractError("evidence has missing or unknown fields")
    if (value["application"], value["environment"]) != (
        contract["application"],
        contract["environment"],
    ):
        raise ContractError("evidence identity does not match the producer")
    for field in ("completionValid", "decryptionSucceeded"):
        if type(value[field]) is not bool:
            raise ContractError(f"{field} must be boolean")
    if type(value["attemptedAt"]) not in (int, float) or value["attemptedAt"] < 0:
        raise ContractError("attemptedAt must be a non-negative timestamp")
    if type(value["durationSeconds"]) not in (int, float) or value["durationSeconds"] < 0:
        raise ContractError("durationSeconds must be non-negative")
    stage = value["failureStage"]
    if stage not in FAILURE_STAGES:
        raise ContractError("evidence has an unsupported failure stage")
    success = value["completionValid"] and value["decryptionSucceeded"] and stage == "none"
    if stage == "none" and not success:
        raise ContractError("successful evidence requires valid completion and decryption")
    if stage != "none" and success:
        raise ContractError("failed evidence cannot report success")
    return {**value, "success": success}


def render_metrics(contract: dict, evidence: dict | None) -> str:
    """Render only bounded state; never serialize source evidence or request material."""
    labels = f'application="{contract["application"]}",environment="{contract["environment"]}"'
    enabled = int(contract["enabled"])
    lines = [
        "# HELP encrypted_completion_monitoring_enabled Whether scheduled monitoring is intentional.",
        "# TYPE encrypted_completion_monitoring_enabled gauge",
        f"encrypted_completion_monitoring_enabled{{{labels}}} {enabled}",
    ]
    if evidence is None:
        return "\n".join(lines) + "\n"
    parsed = parse_evidence(evidence, contract)
    success = int(parsed["success"])
    last_success = parsed["attemptedAt"] if success else 0
    lines.extend(
        [
            "# HELP encrypted_completion_success Last client-side completion and decryption result.",
            "# TYPE encrypted_completion_success gauge",
            f"encrypted_completion_success{{{labels}}} {success}",
            "# HELP encrypted_completion_last_attempt_timestamp_seconds Last bounded attempt time.",
            "# TYPE encrypted_completion_last_attempt_timestamp_seconds gauge",
            f"encrypted_completion_last_attempt_timestamp_seconds{{{labels}}} {parsed['attemptedAt']}",
            "# HELP encrypted_completion_last_success_timestamp_seconds Last successful completion time.",
            "# TYPE encrypted_completion_last_success_timestamp_seconds gauge",
            f"encrypted_completion_last_success_timestamp_seconds{{{labels}}} {last_success}",
            "# HELP encrypted_completion_duration_seconds End-to-end completion/decryption duration, not HTTP polling latency.",
            "# TYPE encrypted_completion_duration_seconds gauge",
            f"encrypted_completion_duration_seconds{{{labels}}} {parsed['durationSeconds']}",
            "# HELP encrypted_completion_failure_stage Finite one-hot completion failure stage.",
            "# TYPE encrypted_completion_failure_stage gauge",
        ]
    )
    for stage in FAILURE_STAGES:
        lines.append(
            f'encrypted_completion_failure_stage{{{labels},stage="{stage}"}} {int(stage == parsed["failureStage"])}'
        )
    return "\n".join(lines) + "\n"
