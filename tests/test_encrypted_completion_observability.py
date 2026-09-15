"""Repository-only contract tests; these fixtures never perform an encrypted request."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts import encrypted_completion_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/observability/tokenplace-encrypted-completion.json"
RULES = ROOT / "platform/observability/rules/encrypted-completion.yaml"


def contract():
    return metrics.load_contract(CONFIG)


def evidence(**changes):
    value = {
        "schemaVersion": 1,
        "application": "tokenplace",
        "environment": "staging",
        "attemptedAt": 1700000000,
        "durationSeconds": 12.5,
        "completionValid": True,
        "decryptionSucceeded": True,
        "failureStage": "none",
    }
    value.update(changes)
    return value


def test_successful_client_side_completion_and_decryption_fixture_is_sanitized():
    rendered = metrics.render_metrics(contract(), evidence())
    assert "encrypted_completion_success" in rendered
    assert " 1\n" in rendered
    assert "duration, not HTTP polling latency" in rendered
    assert "1700000000" in rendered


@pytest.mark.parametrize(
    ("stage", "changes"),
    [
        ("timeout", {}),
        ("compute_unavailable", {}),
        ("malformed_completion", {}),
        ("interrupted", {}),
        ("decryption_failed", {"decryptionSucceeded": False}),
    ],
)
def test_bounded_failure_stages(stage, changes):
    value = evidence(completionValid=False, failureStage=stage, **changes)
    rendered = metrics.render_metrics(contract(), value)
    assert (
        'encrypted_completion_success{application="tokenplace",environment="staging"} 0' in rendered
    )
    assert f'stage="{stage}"}} 1' in rendered


def test_disabled_and_stale_states_are_distinguishable():
    disabled = metrics.render_metrics(contract(), None)
    assert "encrypted_completion_monitoring_enabled" in disabled
    assert disabled.endswith(" 0\n")
    assert "last_attempt" not in disabled
    enabled = contract()
    enabled["enabled"] = True
    stale_candidate = metrics.render_metrics(enabled, evidence(attemptedAt=1))
    assert "monitoring_enabled{application" in stale_candidate and " 1\n" in stale_candidate
    assert "last_attempt_timestamp_seconds" in stale_candidate


def test_evidence_schema_rejects_sensitive_or_identifying_material():
    forbidden = ["prompt", "response", "ciphertext", "key", "credential", "requestIdentity"]
    for field in forbidden:
        value = evidence()
        value[field] = "material-must-not-be-emitted"
        with pytest.raises(metrics.ContractError, match="missing or unknown fields"):
            metrics.render_metrics(contract(), value)
    rendered = metrics.render_metrics(contract(), evidence())
    for marker in ("material-must-not-be-emitted", "prompt=", "ciphertext=", "requestIdentity="):
        assert marker not in rendered


def producer(**changes):
    value = contract()
    value["enabled"] = True
    value.update(changes)
    return value


def test_descriptor_is_disabled_and_complete_but_quota_valid():
    value = contract()
    assert value["enabled"] is False
    assert value["route"] == "/api/v1/chat/completions"
    assert value["method"] == "POST"
    assert quotas.validate_scheduled_producers([value]) == 1


def test_quota_exhaustion_and_exact_exemption():
    value = producer(cadence="60s", timeout="30s", quota={"hourly": 60, "daily": 2000})
    with pytest.raises(quotas.ContractError, match="window=hourly volume=60"):
        quotas.validate_scheduled_producers([value])
    value["exemptions"] = [{"route": value["route"], "method": "POST"}]
    quotas.validate_scheduled_producers([value])


def test_method_mismatch_is_not_exempt():
    value = producer(cadence="60s", timeout="30s", quota={"hourly": 60, "daily": 2000})
    value["exemptions"] = [{"route": value["route"], "method": "GET"}]
    with pytest.raises(quotas.ContractError, match="unsafe scheduled producer"):
        quotas.validate_scheduled_producers([value])


def test_shared_bucket_volume_includes_concurrency_and_all_producers():
    first = producer(cadence="120s", timeout="30s", quota={"hourly": 90, "daily": 100000})
    second = copy.deepcopy(first)
    second["concurrency"] = 2
    with pytest.raises(quotas.ContractError, match="window=hourly volume=90"):
        quotas.validate_scheduled_producers([first, second])


@pytest.mark.parametrize("field", ["cadence", "timeout", "concurrency", "quota", "route", "method"])
def test_missing_schedule_metadata_fails_closed(field):
    value = producer()
    del value[field]
    with pytest.raises(quotas.ContractError, match="missing or unknown metadata"):
        quotas.validate_scheduled_producers([value])


def test_descriptor_contains_no_request_material():
    raw = CONFIG.read_text(encoding="utf-8").lower()
    parsed = json.loads(raw)
    assert parsed["enabled"] is False
    for forbidden in (
        "prompt",
        "response",
        "ciphertext",
        "credentials",
        "request_identity",
        "secret",
    ):
        assert forbidden not in raw


def test_rules_distinguish_stale_from_intentionally_disabled_monitoring():
    rules = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"][0]["rules"]
    stale, disabled = rules
    assert stale["alert"] == "EncryptedCompletionProducerStale"
    assert "encrypted_completion_monitoring_enabled == 1" in stale["expr"]
    assert "encrypted_completion_last_attempt_timestamp_seconds" in stale["expr"]
    assert disabled == {
        "record": "encrypted_completion_monitoring_disabled",
        "expr": "encrypted_completion_monitoring_enabled == 0",
    }
