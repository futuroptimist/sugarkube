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


def producer(enabled=True):
    value = contract()["producers"][0]
    value["enabled"] = enabled
    return value


def test_success_fixture_proves_only_client_decryption_and_response_validity():
    result = metrics.validate_evidence(evidence())
    output = metrics.render_metrics(producer(), result, now=1_700_000_003)
    assert "encrypted_completion_success" in output
    assert "encrypted_completion_last_success_timestamp_seconds" in output
    assert "encrypted_completion_attempt_timestamp_seconds" in output
    assert "encrypted_completion_duration_seconds" in output
    assert "HTTP polling latency" in output


@pytest.mark.parametrize(
    "stage", ["timeout", "compute_unavailable", "malformed_completion", "interrupted"]
)
def test_finite_failure_stages_are_distinguishable(stage):
    output = metrics.render_metrics(producer(), evidence(stage), now=1_700_000_003)
    assert f'failure_stage="{stage}"' in output
    assert "encrypted_completion_success" in output and " 0\n" in output


def test_failed_attempt_preserves_last_success_timestamp():
    output = metrics.render_metrics(producer(), evidence("timeout"), now=1_700_000_003)
    assert "encrypted_completion_last_success_timestamp_seconds" in output
    assert " 1699999000\n" in output


def test_future_evidence_is_rejected_with_bounded_clock_skew():
    value = evidence()
    value["attemptedAt"] = value["completedAt"] = value["lastSuccessfulAt"] = 2_000
    metrics.validate_evidence(value, now=1_700)
    with pytest.raises(ValueError, match="too far in the future"):
        metrics.validate_evidence(value, now=1_699)


@pytest.mark.parametrize(("field", "value"), [("outcome", {}), ("failureStage", {})])
def test_malformed_evidence_metadata_is_safely_rejected(field, value):
    record = evidence()
    record[field] = value
    with pytest.raises(ValueError):
        metrics.validate_evidence(record)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(producer="bad identity"), "producer is invalid"),
        (lambda value: value.update(attemptedAt=0), "attemptedAt is invalid"),
        (lambda value: value.update(completedAt=False), "completedAt is invalid"),
        (lambda value: value.update(lastSuccessfulAt=-1), "lastSuccessfulAt is invalid"),
        (lambda value: value.update(durationSeconds=float("inf")), "duration is invalid"),
        (lambda value: value.update(responseValid=1), "assertions are invalid"),
        (lambda value: value.update(failureStage="timeout"), "failure stage contradict"),
        (
            lambda value: value.update(clientDecryptionVerified=False),
            "success requires client decryption",
        ),
        (lambda value: value.update(completedAt=1_699_999_999), "completion predates"),
        (
            lambda value: value.update(lastSuccessfulAt=1_700_000_000),
            "must update lastSuccessfulAt",
        ),
        (
            lambda value: value.update(
                outcome="failure",
                failureStage="timeout",
                clientDecryptionVerified=False,
                responseValid=False,
                lastSuccessfulAt=1_700_000_001,
            ),
            "failed evidence has an invalid",
        ),
    ],
)
def test_evidence_relationships_fail_closed(mutation, message):
    record = evidence()
    mutation(record)
    with pytest.raises(ValueError, match=message):
        metrics.validate_evidence(record, now=1_700_000_003)


@pytest.mark.parametrize("now", [False, float("nan")])
def test_invalid_injected_clocks_are_rejected(now):
    with pytest.raises(ValueError, match="current time is invalid"):
        metrics.validate_evidence(evidence(), now=now)
    with pytest.raises(ValueError, match="current time is invalid"):
        metrics.render_metrics(producer(), now=now)


def test_dynamic_prometheus_label_injection_is_rejected():
    value = producer(False)
    value["application"] = 'app"\\\ninjected_metric 1'
    with pytest.raises(ValueError, match="producer identity is invalid"):
        metrics.render_metrics(value)


def test_renderer_rejects_malformed_producer_metadata_and_identity_mismatch():
    with pytest.raises(ValueError, match="producer metadata is invalid"):
        metrics.render_metrics(None)
    value = producer()
    value["cadence"] = "immediate"
    with pytest.raises(ValueError, match="producer cadence is invalid"):
        metrics.render_metrics(value)
    record = evidence()
    record["application"] = "another-app"
    with pytest.raises(ValueError, match="identity contradicts producer"):
        metrics.render_metrics(producer(), record, now=1_700_000_003)


def test_stale_and_intentionally_disabled_states_are_distinguishable():
    producer = contract()["producers"][0]
    output = metrics.render_metrics(producer)
    assert "encrypted_completion_monitoring_enabled" in output
    assert "encrypted_completion_monitoring_enabled" in output and " 0\n" in output
    assert "attempt_timestamp" not in output  # absence/staleness is not rewritten as failure
    assert 'state="disabled"} 1' in output


def test_lifecycle_states_are_deterministic_for_enabled_producers():
    value = producer()
    assert 'state="never_attempted"} 1' in metrics.render_metrics(value, now=1_700_000_003)
    assert 'state="fresh"} 1' in metrics.render_metrics(value, evidence(), now=1_700_000_003)
    assert 'state="failed"} 1' in metrics.render_metrics(
        value, evidence("timeout"), now=1_700_000_003
    )
    assert 'state="stale"} 1' in metrics.render_metrics(
        value, evidence("interrupted"), now=1_700_000_003 + 6 * 3600 + 241
    )


def test_disabled_producer_rejects_execution_evidence_and_enabled_is_boolean():
    with pytest.raises(ValueError, match="disabled producer"):
        metrics.render_metrics(producer(False), evidence())
    value = producer(False)
    value["enabled"] = 0
    with pytest.raises(ValueError, match="enabled state"):
        metrics.render_metrics(value)


def test_telemetry_and_evidence_reject_sensitive_or_request_material():
    sensitive = ("secret", "payload", "ciphertext", "key", "credential", "requestIdentity")
    value = evidence()
    for field in sensitive:
        mutated = copy.deepcopy(value)
        mutated[field] = "forbidden"
        with pytest.raises(ValueError, match="exact sanitized schema"):
            metrics.validate_evidence(mutated)
    serialized = (json.dumps(contract()) + metrics.render_metrics(producer(), value)).lower()
    assert not any(term.lower() in serialized for term in sensitive)


def test_repository_descriptor_is_disabled_complete_and_quota_safe():
    value = contract()
    assert quotas.validate_completion_contract(value) == 1
    producer = value["producers"][0]
    assert producer["enabled"] is False
    assert (producer["cadence"], producer["timeout"], producer["concurrency"]) == ("6h", "240s", 1)
    assert producer["requestMultiplicity"] is None


def test_enabled_quota_exhaustion_and_exact_exemption():
    value = contract()
    producer = value["producers"][0]
    producer.update(enabled=True, cadence="1m", timeout="30s", requestMultiplicity=1)
    with pytest.raises(quotas.ContractError, match="unsafe completion schedule"):
        quotas.validate_completion_contract(value)
    producer["exemptions"] = [{"route": producer["route"], "method": producer["method"]}]
    quotas.validate_completion_contract(value)


def test_exemption_method_mismatch_fails_and_shared_bucket_aggregates():
    value = contract()
    first = value["producers"][0]
    first.update(enabled=True, cadence="10m", requestMultiplicity=1)
    first["limits"] = {"hourly": 20, "daily": 310}
    first["exemptions"] = [{"route": first["route"], "method": "GET"}]
    second = copy.deepcopy(first)
    second["name"] = "second"
    value["producers"].append(second)
    with pytest.raises(quotas.ContractError, match="window=daily volume=288"):
        quotas.validate_completion_contract(value)


@pytest.mark.parametrize(
    "field",
    [
        "cadence",
        "timeout",
        "concurrency",
        "requestMultiplicity",
        "route",
        "method",
        "limits",
        "failureStages",
    ],
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value, item: value.update(extra=True), "top-level fields"),
        (lambda value, item: value.update(schemaVersion=2), "schemaVersion/producers"),
        (lambda value, item: item.update(name=""), "invalid name"),
        (lambda value, item: item.update(enabled=1), "environment/enabled"),
        (
            lambda value, item: value["producers"].append(copy.deepcopy(item)),
            "identity is duplicated",
        ),
        (lambda value, item: item.update(timeout=item["cadence"]), "shorter than cadence"),
        (lambda value, item: item.update(enabled=True), "requires requestMultiplicity"),
        (lambda value, item: item.update(method=[]), "unknown method"),
        (lambda value, item: item.update(safetyMargin=True), "invalid safetyMargin"),
        (lambda value, item: item.update(limits=[]), "ambiguous limits"),
        (lambda value, item: item.update(exemptions={}), "malformed exemptions"),
        (lambda value, item: item.update(exemptions=[{}]), "malformed exemptions"),
        (
            lambda value, item: item.update(exemptions=[{"route": item["route"], "method": []}]),
            "malformed exemptions",
        ),
        (
            lambda value, item: item.update(
                exemptions=[
                    {"route": item["route"], "method": item["method"]},
                    {"route": item["route"], "method": item["method"]},
                ]
            ),
            "duplicate exemptions",
        ),
    ],
)
def test_completion_contract_metadata_errors_are_deterministic(mutation, message):
    value = contract()
    mutation(value, value["producers"][0])
    with pytest.raises(quotas.ContractError, match=message):
        quotas.validate_completion_contract(value)


def test_completion_contract_rejects_conflicting_shared_policy():
    value = contract()
    item = value["producers"][0]
    key = (item["application"], item["environment"], item["bucket"])
    with pytest.raises(quotas.ContractError, match="contradictory shared-bucket policy"):
        quotas.validate_completion_contract(value, shared_policies={key: ("unlimited", 0)})


def test_request_multiplicity_is_distinct_from_concurrency():
    value = contract()
    item = value["producers"][0]
    item.update(enabled=True, cadence="1h", concurrency=2, requestMultiplicity=3)
    item["limits"] = {"hourly": 7, "daily": 144}
    item["safetyMargin"] = 0
    with pytest.raises(quotas.ContractError, match="window=daily volume=144"):
        quotas.validate_completion_contract(value)


def test_main_identifies_malformed_completion_json(tmp_path, capsys):
    malformed = tmp_path / "completion.json"
    malformed.write_text('{"private": "JSON_SENTINEL"', encoding="utf-8")
    assert quotas.main(["--env", "staging", "--completion-contract", str(malformed)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "probe quota validation failed: JSON input is malformed\n"
    assert "JSON_SENTINEL" not in captured.err
