import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import encrypted_completion_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/observability/encrypted-completion-producers.yaml"
SCHEMA = ROOT / "platform/observability/encrypted-completion-metrics.json"


def producer():
    return {
        "application": "example",
        "environment": "staging",
        "producer": "encrypted-completion",
        "enabled": True,
        "cadence": "15m",
        "timeout": "2m",
        "concurrency": 1,
        "bucket": "inference",
        "limits": {"hourly": 10, "daily": 100},
        "route": "/api/v1/chat/completions",
        "method": "POST",
        "exemptions": [],
        "safety_margin": 0.2,
        "unlimited_operational": False,
        "failure_stages": [
            "timeout",
            "compute_unavailable",
            "malformed_completion",
            "interrupted",
            "decryption_failed",
        ],
    }


def result(*, stage="none"):
    successful = stage == "none"
    return {
        "schemaVersion": 1,
        "application": "example",
        "environment": "staging",
        "attemptedAt": 1_800_000_000,
        "durationSeconds": 12.5,
        "outcome": "success" if successful else "failure",
        "failureStage": stage,
        "clientDecrypted": successful,
        "responseValid": successful,
    }


def test_successful_client_decryption_and_completion_fixture_is_sanitized():
    rendered = metrics.render_metrics(result())
    assert "encrypted_completion_success" in rendered
    assert " 1\n" in rendered
    assert 'stage="none"' in rendered
    assert "1800000000" in rendered and "12.5" in rendered


@pytest.mark.parametrize(
    "stage",
    ["timeout", "compute_unavailable", "malformed_completion", "interrupted"],
)
def test_bounded_failure_stage_fixtures(stage):
    rendered = metrics.render_metrics(result(stage=stage), last_success=1_799_999_000)
    assert "encrypted_completion_success" in rendered
    assert f'stage="{stage}"' in rendered
    assert "1799999000" in rendered


def test_result_schema_rejects_unbounded_or_sensitive_evidence():
    for field in (
        "prompt",
        "response",
        "payload",
        "ciphertext",
        "key",
        "credential",
        "authorization",
        "request_id",
        "user",
        "session",
    ):
        unsafe = result()
        unsafe[field] = "must-not-appear"
        with pytest.raises(ValueError, match="exact bounded schema"):
            metrics.render_metrics(unsafe)
    with pytest.raises(ValueError, match="inconsistent"):
        metrics.render_metrics(result(stage="network_error"))


def test_descriptor_is_disabled_and_schema_distinguishes_stale_and_disabled():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert quotas.validate_scheduled_producers(contract) == 1
    declaration = contract["producers"][0]
    assert declaration["enabled"] is False
    assert declaration["route"] == "/api/v1/chat/completions"
    assert declaration["method"] == "POST"
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["states"]["disabled"] != schema["states"]["stale"]
    assert (
        "HTTP polling latency" in schema["metricFamilies"]["encrypted_completion_duration_seconds"]
    )


def test_enabled_schedule_fails_closed_at_budget_and_exact_exemption_passes():
    item = producer()
    item["cadence"] = "6m"
    item["limits"] = {"hourly": 12, "daily": 1000}
    with pytest.raises(quotas.ContractError, match="window=hourly volume=10"):
        quotas.validate_scheduled_producers({"version": 1, "producers": [item]})
    item["exemptions"] = [{"route": item["route"], "method": item["method"]}]
    quotas.validate_scheduled_producers({"version": 1, "producers": [item]})


def test_exemption_method_mismatch_and_shared_bucket_volume_fail_closed():
    one = producer()
    one["cadence"] = "10m"
    one["limits"] = {"hourly": 13, "daily": 1000}
    one["exemptions"] = [{"route": one["route"], "method": "GET"}]
    two = copy.deepcopy(one)
    two["producer"] = "second"
    with pytest.raises(quotas.ContractError, match="window=hourly volume=12"):
        quotas.validate_scheduled_producers({"version": 1, "producers": [one, two]})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cadence", None),
        ("timeout", "20m"),
        ("concurrency", 0),
        ("route", "https://example.invalid/path"),
        ("method", "TRACE"),
        ("limits", {"daily": 100}),
        ("failure_stages", []),
    ],
)
def test_missing_or_ambiguous_schedule_metadata_fails_closed(field, value):
    item = producer()
    item[field] = value
    with pytest.raises(quotas.ContractError):
        quotas.validate_scheduled_producers({"version": 1, "producers": [item]})


def test_disabled_and_unlimited_semantics_are_explicit():
    item = producer()
    item.update(enabled=False, cadence="2m", timeout="1m", concurrency=1000)
    quotas.validate_scheduled_producers({"version": 1, "producers": [item]})
    item.update(enabled=True, unlimited_operational=True, limits=None, exemptions=[])
    quotas.validate_scheduled_producers({"version": 1, "producers": [item]})
