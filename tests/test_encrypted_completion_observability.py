"""Focused repository-only contracts for encrypted completion observability."""

import copy
import json
from pathlib import Path

import pytest

from scripts.encrypted_completion_metrics import render_metrics
from scripts.validate_probe_quotas import ContractError, validate_declarative_schedules

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "config/observability/encrypted-completion.json"


def descriptor():
    return json.loads(DESCRIPTOR.read_text())


def enabled():
    value = descriptor()
    value["producers"][0]["enabled"] = True
    return value


def result(stage="none"):
    success = stage == "none"
    return {
        "schemaVersion": 1,
        "completedAt": 1000,
        "durationSeconds": 12.5,
        "failureStage": stage,
        "decrypted": success,
        "valid": success,
    }


def test_successful_client_fixture_exports_only_sanitized_completion_metrics():
    metrics = render_metrics(enabled()["producers"][0], result(), now=1000)
    assert "encrypted_completion_success" in metrics
    assert "encrypted_completion_last_success_timestamp_seconds" in metrics
    assert "encrypted_completion_duration_seconds" in metrics
    assert 'stage="none"' in metrics


@pytest.mark.parametrize(
    "stage", ["timeout", "compute_unavailable", "malformed_completion", "interrupted"]
)
def test_bounded_failure_stages(stage):
    metrics = render_metrics(enabled()["producers"][0], result(stage), now=1000)
    assert 'encrypted_completion_success{application="tokenplace",environment="prod"} 0' in metrics
    assert f'stage="{stage}"' in metrics
    assert "last_success" not in metrics


def test_disabled_and_stale_states_are_distinguishable():
    assert render_metrics(descriptor()["producers"][0], None) == (
        'encrypted_completion_monitoring_enabled{application="tokenplace",environment="prod"} 0\n'
    )
    rules = (ROOT / "platform/observability/rules/tokenplace-production.yaml").read_text()
    assert "TokenplaceEncryptedCompletionStale" in rules
    assert "encrypted_completion_monitoring_enabled" in rules
    assert "encrypted_completion_attempt_timestamp_seconds" in rules


def test_quota_exhaustion_exact_exemption_and_method_mismatch():
    value = enabled()
    producer = value["producers"][0]
    producer.update(cadence="1m", timeout="30s", safetyMargin=0)
    producer["limits"] = {"hourly": 60, "daily": 2000}
    with pytest.raises(ContractError, match="unsafe schedule"):
        validate_declarative_schedules(value)
    producer["exemptions"] = [{"route": producer["route"], "method": "POST"}]
    validate_declarative_schedules(value)
    producer["exemptions"][0]["method"] = "GET"
    with pytest.raises(ContractError, match="unsafe schedule"):
        validate_declarative_schedules(value)


def test_shared_bucket_volume_and_missing_metadata_fail_closed():
    value = enabled()
    first = value["producers"][0]
    first.update(cadence="2m", timeout="30s", safetyMargin=0)
    first["limits"] = {"hourly": 60, "daily": 2000}
    value["producers"].append(copy.deepcopy(first))
    with pytest.raises(ContractError, match="volume=60"):
        validate_declarative_schedules(value)
    del value["producers"][0]["method"]
    with pytest.raises(ContractError, match="metadata"):
        validate_declarative_schedules(value)


def test_descriptor_and_evidence_reject_sensitive_or_unbounded_material():
    serialized = DESCRIPTOR.read_text().lower()
    forbidden = ("prompt", "response", "ciphertext", "privatekey", "credential", "requestidentity")
    assert not any(term in serialized for term in forbidden)
    producer = enabled()["producers"][0]
    for key in forbidden:
        evidence = result()
        evidence[key] = "sensitive"
        with pytest.raises(ValueError, match="exact bounded schema"):
            render_metrics(producer, evidence, now=1000)
