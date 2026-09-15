"""Repository-only encrypted-completion contract tests."""

import copy
import json
from pathlib import Path

import pytest

from scripts import encrypted_completion_metrics as metrics
from scripts import validate_probe_quotas as quotas

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/observability/encrypted-completion.json"


def contract():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def evidence(stage="none"):
    success = stage == "none"
    return {
        "schemaVersion": 1,
        "producer": "tokenplace-client-completion-staging",
        "application": "tokenplace",
        "environment": "staging",
        "outcome": "success" if success else "failure",
        "failureStage": stage,
        "attemptedAt": 1_700_000_000,
        "completedAt": 1_700_000_003,
        "lastSuccessfulAt": 1_700_000_003 if success else 1_699_999_000,
        "durationSeconds": 3.25,
        "clientDecryptionVerified": success,
        "responseValid": success,
    }


def test_success_fixture_proves_only_client_decryption_and_response_validity():
    result = metrics.validate_evidence(evidence())
    output = metrics.render_metrics(contract()["producers"][0], result)
    assert "encrypted_completion_success" in output
    assert "encrypted_completion_last_success_timestamp_seconds" in output
    assert "encrypted_completion_attempt_timestamp_seconds" in output
    assert "encrypted_completion_duration_seconds" in output
    assert "HTTP polling latency" in output


@pytest.mark.parametrize(
    "stage", ["timeout", "compute_unavailable", "malformed_completion", "interrupted"]
)
def test_finite_failure_stages_are_distinguishable(stage):
    output = metrics.render_metrics(contract()["producers"][0], evidence(stage))
    assert f'failure_stage="{stage}"' in output
    assert "encrypted_completion_success" in output and " 0\n" in output


def test_failed_attempt_preserves_last_success_timestamp():
    output = metrics.render_metrics(contract()["producers"][0], evidence("timeout"))
    assert "encrypted_completion_last_success_timestamp_seconds" in output
    assert " 1699999000\n" in output


def test_future_evidence_is_rejected_with_bounded_clock_skew():
    value = evidence()
    value["attemptedAt"] = value["completedAt"] = value["lastSuccessfulAt"] = 2_000
    metrics.validate_evidence(value, now=1_700)
    with pytest.raises(ValueError, match="too far in the future"):
        metrics.validate_evidence(value, now=1_699)


def test_dynamic_prometheus_labels_are_escaped():
    producer = contract()["producers"][0]
    producer.update(name='producer"\\\n', application='app"\\\n', environment='stage"\\\n')
    output = metrics.render_metrics(producer)
    assert 'application="app\\"\\\\\\n"' in output
    assert 'environment="stage\\"\\\\\\n"' in output
    assert 'producer="producer\\"\\\\\\n"' in output


def test_stale_and_intentionally_disabled_states_are_distinguishable():
    producer = contract()["producers"][0]
    output = metrics.render_metrics(producer)
    assert "encrypted_completion_monitoring_enabled" in output
    assert output.endswith(" 0\n")
    assert "attempt_timestamp" not in output  # absence/staleness is not rewritten as failure


def test_telemetry_and_evidence_reject_sensitive_or_request_material():
    sensitive = ("secret", "payload", "ciphertext", "key", "credential", "requestIdentity")
    value = evidence()
    for field in sensitive:
        mutated = copy.deepcopy(value)
        mutated[field] = "forbidden"
        with pytest.raises(ValueError, match="exact sanitized schema"):
            metrics.validate_evidence(mutated)
    serialized = (
        json.dumps(contract()) + metrics.render_metrics(contract()["producers"][0], value)
    ).lower()
    assert not any(term.lower() in serialized for term in sensitive)


def test_repository_descriptor_is_disabled_complete_and_quota_safe():
    value = contract()
    assert quotas.validate_completion_contract(value) == 1
    producer = value["producers"][0]
    assert producer["enabled"] is False
    assert (producer["cadence"], producer["timeout"], producer["concurrency"]) == ("6h", "240s", 1)


def test_enabled_quota_exhaustion_and_exact_exemption():
    value = contract()
    producer = value["producers"][0]
    producer.update(enabled=True, cadence="1m", timeout="30s")
    with pytest.raises(quotas.ContractError, match="unsafe completion schedule"):
        quotas.validate_completion_contract(value)
    producer["exemptions"] = [{"route": producer["route"], "method": producer["method"]}]
    quotas.validate_completion_contract(value)


def test_exemption_method_mismatch_fails_and_shared_bucket_aggregates():
    value = contract()
    first = value["producers"][0]
    first.update(enabled=True, cadence="10m")
    first["limits"] = {"hourly": 20, "daily": 310}
    first["exemptions"] = [{"route": first["route"], "method": "GET"}]
    second = copy.deepcopy(first)
    second["name"] = "second"
    value["producers"].append(second)
    with pytest.raises(quotas.ContractError, match="window=daily volume=288"):
        quotas.validate_completion_contract(value)


@pytest.mark.parametrize(
    "field", ["cadence", "timeout", "concurrency", "route", "method", "limits", "failureStages"]
)
def test_missing_metadata_fails_closed(field):
    value = contract()
    del value["producers"][0][field]
    with pytest.raises(quotas.ContractError):
        quotas.validate_completion_contract(value)


@pytest.mark.parametrize("malformed", [["none", {}], "none", None])
def test_malformed_failure_stages_fail_with_contract_error(malformed):
    value = contract()
    value["producers"][0]["failureStages"] = malformed
    with pytest.raises(quotas.ContractError, match="finite vocabulary"):
        quotas.validate_completion_contract(value)


def test_cross_inventory_shared_bucket_is_rejected():
    completion = contract()
    producer = completion["producers"][0]
    producer["enabled"] = True
    probes = {
        "probes": [
            {
                "application": producer["application"],
                "environment": producer["environment"],
                "bucket": producer["bucket"],
                "enabled": True,
                "unlimited_operational": False,
            }
        ]
    }
    with pytest.raises(quotas.ContractError, match="reuse a metered shared bucket"):
        quotas.reject_cross_inventory_bucket_reuse(probes, completion)


def test_main_identifies_malformed_completion_json(tmp_path, capsys):
    malformed = tmp_path / "completion.json"
    malformed.write_text('{"private": "JSON_SENTINEL"', encoding="utf-8")
    assert quotas.main(["--env", "staging", "--completion-contract", str(malformed)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "probe quota validation failed: JSON input is malformed\n"
    assert "JSON_SENTINEL" not in captured.err
