import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "static_plan", Path(__file__).parents[1] / "scripts/tokenplace_static_429_plan.py"
)
plan = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(plan)

CONFIGURATION = b"opaque reviewed edge configuration bytes\n"


def timestamp(offset=0):
    return (datetime(2026, 9, 26, 12, tzinfo=timezone.utc) + timedelta(seconds=offset)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def valid_input():
    return {
        "schema_version": 1,
        "lifecycle": "authorized-static-emulation",
        "created_at": timestamp(),
        "target": {
            "scheme": "https",
            "authority": "staging.token.place",
            "follow_redirects": False,
            "emulation_routes": [
                {"method": "GET", "path": "/", "expected_status": 429},
                {"method": "GET", "path": "/api/v1/meta", "expected_status": 429},
            ],
            "health_controls": [
                {"method": "GET", "path": "/livez", "expected_status": 200},
                {"method": "GET", "path": "/healthz", "expected_status": 200},
            ],
        },
        "rule_attestation": {
            "attested_at": timestamp(-60),
            "reviewer": "reviewer@example.test",
            "reviewer_decision": "scope-exactly-approved",
            "rule_identity_sha256": "a" * 64,
            "reviewed_configuration_sha256": hashlib.sha256(CONFIGURATION).hexdigest(),
            "scope_authority": "staging.token.place",
            "scope_methods": ["GET"],
            "scope_paths": ["/", "/api/v1/meta"],
        },
        "authorization": {
            "authorized_at": timestamp(-60),
            "authorizer": "authorizer@example.test",
            "rehearsal_starts_at": timestamp(60),
            "rehearsal_ends_at": timestamp(360),
            "review_ends_at": timestamp(600),
            "expires_at": timestamp(600),
            "removal_deadline_at": timestamp(600),
            "removal_owner": "edge-owner@example.test",
            "handoff": "staging-edge-operations",
            "escalation": "staging-incident-commander",
        },
        "policy": {
            "max_evidence_age_seconds": 300,
            "max_future_skew_seconds": 30,
            "max_rehearsal_seconds": 300,
            "max_review_seconds": 300,
            "max_retention_seconds": 86400,
            "request_timeout_seconds": 5,
            "retention_seconds": 3600,
        },
    }


def build(value=None, configuration=CONFIGURATION):
    value = valid_input() if value is None else value
    raw = json.dumps(value, separators=(",", ":")).encode()
    return plan.build_plan(raw, configuration)


def test_valid_plan_is_stable_bound_and_separates_health_controls():
    source = valid_input()
    first = build(source)
    second = build(source)
    assert first == second
    assert (
        first["input_sha256"]
        == hashlib.sha256(json.dumps(source, separators=(",", ":")).encode()).hexdigest()
    )
    assert [route["expected_status"] for route in first["target"]["emulation_routes"]] == [429, 429]
    assert [route["expected_status"] for route in first["target"]["health_controls"]] == [200, 200]
    assert first["capabilities"] == {"network": False, "mutation": False, "quota_stimulus": False}
    assert first["claims_are_declarations"] is True
    assert first["cryptographic_verification_performed"] is False


@pytest.mark.parametrize("lifecycle", [None, "quota-exhaustion", "preflight-validated"])
def test_requires_exact_lifecycle(lifecycle):
    value = valid_input()
    if lifecycle is None:
        del value["lifecycle"]
    else:
        value["lifecycle"] = lifecycle
    with pytest.raises(plan.PlanError):
        build(value)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("scheme", "http"),
        ("authority", "token.place"),
        ("authority", "prod.token.place"),
        ("authority", "staging.token.place:443"),
        ("authority", "user@staging.token.place"),
        ("authority", "staging.token.place?x=1"),
        ("authority", "staging.token.place#x"),
        ("follow_redirects", True),
    ],
)
def test_rejects_noncanonical_target_and_redirects(field, bad):
    value = valid_input()
    value["target"][field] = bad
    with pytest.raises(plan.PlanError):
        build(value)


@pytest.mark.parametrize("path", ["//", "/./", "/api/v1/meta/", "/api/v1/meta?x=1", "/healthz"])
def test_rejects_changed_or_normalized_emulation_paths(path):
    value = valid_input()
    value["target"]["emulation_routes"][0]["path"] = path
    with pytest.raises(plan.PlanError, match="exact ordered route"):
        build(value)


def test_rejects_broadened_rule_scope_and_hash_mismatch():
    value = valid_input()
    value["rule_attestation"]["scope_paths"].append("/healthz")
    with pytest.raises(plan.PlanError, match="scope"):
        build(value)
    with pytest.raises(plan.PlanError, match="hash"):
        build(valid_input(), b"different bytes")


@pytest.mark.parametrize(
    "change",
    [
        {"attested_at": timestamp(-301)},
        {"attested_at": timestamp(31)},
        {"rehearsal_starts_at": timestamp(-1)},
        {"rehearsal_ends_at": timestamp(361)},
        {"review_ends_at": timestamp(601)},
        {"expires_at": timestamp(359)},
    ],
)
def test_rejects_stale_future_or_inconsistent_windows(change):
    value = valid_input()
    destination = value["rule_attestation"] if "attested_at" in change else value["authorization"]
    destination.update(change)
    with pytest.raises(plan.PlanError):
        build(value)


def test_strict_schema_duplicate_fields_and_policy_values():
    value = valid_input()
    value["surprise"] = True
    with pytest.raises(plan.PlanError, match="unknown"):
        build(value)
    raw = json.dumps(valid_input()).replace(
        '"schema_version": 1', '"schema_version": 1, "schema_version": 1'
    )
    with pytest.raises(plan.PlanError, match="duplicate"):
        plan.build_plan(raw.encode(), CONFIGURATION)
    value = valid_input()
    del value["policy"]["request_timeout_seconds"]
    with pytest.raises(plan.PlanError, match="missing"):
        build(value)
    value = valid_input()
    value["policy"]["retention_seconds"] = 999999
    with pytest.raises(plan.PlanError, match="retention"):
        build(value)


@pytest.mark.parametrize(
    "field", ["cookie", "response_body", "request_id", "raw_rule_expression", "signature"]
)
def test_rejects_prohibited_privacy_fields(field):
    value = valid_input()
    value["authorization"][field] = "sensitive"
    with pytest.raises(plan.PlanError, match="privacy"):
        build(value)


def test_output_is_exclusive_and_unchanged_on_second_write(tmp_path):
    output = tmp_path / "plan.json"
    generated = build()
    plan.write_plan(output, generated)
    original = output.read_bytes()
    with pytest.raises(plan.PlanError, match="overwrite"):
        plan.write_plan(output, {"changed": True})
    assert output.read_bytes() == original
    assert output.stat().st_mode & 0o777 == 0o600


def test_module_has_no_network_or_live_operation_capability():
    source = (Path(__file__).parents[1] / "scripts/tokenplace_static_429_plan.py").read_text()
    prohibited = (
        "socket",
        "requests",
        "urllib",
        "http.client",
        "subprocess",
        "tokenplace_incident_drill",
    )
    assert all(name not in source for name in prohibited)
