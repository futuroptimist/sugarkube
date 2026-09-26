import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).parents[1] / "scripts" / "tokenplace_static_429_plan.py"
SPEC = importlib.util.spec_from_file_location("static_429_plan", PATH)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def valid_input():
    return {
        "schema_version": 1,
        "lifecycle": "authorized-static-emulation",
        "planned_at": "2026-09-26T12:00:00Z",
        "authorization": {
            "evidence_at": "2026-09-26T11:55:00Z",
            "expires_at": "2026-09-26T13:00:00Z",
            "rehearsal_starts_at": "2026-09-26T12:05:00Z",
            "rehearsal_ends_at": "2026-09-26T12:20:00Z",
            "review_ends_at": "2026-09-26T12:30:00Z",
            "reviewer": "edge-reviewer",
            "reviewer_decision": "approved",
            "rule_identity_sha256": "a" * 64,
            "removal_owner": "edge-owner",
            "handoff": "staging-operations",
            "escalation": "staging-incident-commander",
        },
        "rule_attestation": {
            "authority": "staging.token.place",
            "method": "GET",
            "paths": ["/", "/api/v1/meta"],
            "rule_identity_sha256": "a" * 64,
            "reviewed_configuration_sha256": "b" * 64,
            "reviewer": "edge-reviewer",
            "reviewer_decision": "approved",
        },
        "policy": {
            "freshness_seconds": 600,
            "retention_seconds": 3600,
            "timeout_seconds": 5,
            "max_rehearsal_seconds": 900,
            "max_review_seconds": 600,
            "max_authorization_seconds": 3900,
        },
        "targets": [
            {
                "method": method,
                "url": url,
                "expected_status": status,
                "role": role,
                "follow_redirects": False,
            }
            for method, url, status, role in planner.TARGETS
        ],
    }


def payload(value=None):
    return json.dumps(value or valid_input(), separators=(",", ":")).encode()


def test_valid_plan_is_stable_hash_bound_and_separates_health_controls():
    raw = payload()
    first = planner.load_and_validate(raw)
    assert first == planner.load_and_validate(raw)
    assert first["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert [target["role"] for target in first["targets"]] == [
        "emulation",
        "emulation",
        "health-control",
        "health-control",
    ]
    assert first["claims"]["quota_exhaustion_evidence"] is False
    assert first["claims"]["network_observation_authorized"] is False


def test_output_is_exclusive_and_unchanged(tmp_path):
    output = tmp_path / "plan.json"
    plan = planner.load_and_validate(payload())
    planner.write_plan(plan, output)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        planner.write_plan(plan, output)
    assert output.read_bytes() == original


@pytest.mark.parametrize("lifecycle", [None, "quota-exhaustion", "preflight-validated"])
def test_explicit_lifecycle_is_required(lifecycle):
    value = valid_input()
    if lifecycle is None:
        del value["lifecycle"]
    else:
        value["lifecycle"] = lifecycle
    with pytest.raises(planner.PlanError):
        planner.load_and_validate(payload(value))


@pytest.mark.parametrize(
    "url",
    [
        "https://token.place/",
        "https://staging.token.place:443/",
        "https://user@staging.token.place/",
        "https://staging.token.place/?x=1",
        "https://staging.token.place/#x",
        "https://staging.token.place//",
        "http://staging.token.place/",
    ],
)
def test_noncanonical_target_variants_are_rejected(url):
    value = valid_input()
    value["targets"][0]["url"] = url
    with pytest.raises(planner.PlanError, match="noncanonical"):
        planner.load_and_validate(payload(value))


def test_redirects_broad_scope_and_changed_method_are_rejected():
    for mutate in (
        lambda v: v["targets"][0].update(follow_redirects=True),
        lambda v: v["rule_attestation"]["paths"].append("/healthz"),
        lambda v: v["rule_attestation"].update(method="POST"),
    ):
        value = valid_input()
        mutate(value)
        with pytest.raises(planner.PlanError):
            planner.load_and_validate(payload(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_at", "2026-09-26T11:49:59Z"),
        ("evidence_at", "2026-09-26T12:00:01Z"),
        ("expires_at", "2026-09-26T12:29:59Z"),
        ("rehearsal_ends_at", "2026-09-26T12:05:00Z"),
        ("review_ends_at", "not-a-time"),
    ],
)
def test_stale_future_and_contradictory_windows_are_rejected(field, value):
    document = valid_input()
    document["authorization"][field] = value
    with pytest.raises(planner.PlanError):
        planner.load_and_validate(payload(document))


def test_unknown_duplicate_missing_policy_and_bad_hash_are_rejected():
    value = valid_input()
    value["unexpected"] = True
    with pytest.raises(planner.PlanError):
        planner.load_and_validate(payload(value))
    raw = payload().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
    with pytest.raises(planner.PlanError, match="duplicate"):
        planner.load_and_validate(raw)
    value = valid_input()
    del value["policy"]["timeout_seconds"]
    with pytest.raises(planner.PlanError):
        planner.load_and_validate(payload(value))
    value = valid_input()
    value["rule_attestation"]["rule_identity_sha256"] = "A" * 64
    with pytest.raises(planner.PlanError, match="SHA-256"):
        planner.load_and_validate(payload(value))
    value = valid_input()
    value["authorization"]["rule_identity_sha256"] = "c" * 64
    with pytest.raises(planner.PlanError, match="does not match"):
        planner.load_and_validate(payload(value))


@pytest.mark.parametrize(
    "key",
    [
        "credentials",
        "cookies",
        "response_body",
        "request_id",
        "raw_rule_expression",
        "query_string",
        "private_url",
        "sensitive_headers",
        "prompt",
        "ciphertext",
        "arbitrary_error",
    ],
)
def test_privacy_fields_are_rejected(key):
    value = valid_input()
    value[key] = "redacted"
    with pytest.raises(planner.PlanError, match="privacy"):
        planner.load_and_validate(payload(value))


def test_module_has_no_network_process_or_incident_runner_capability():
    source = PATH.read_text()
    for forbidden in (
        "socket",
        "requests",
        "urllib",
        "http.client",
        "subprocess",
        "tokenplace_incident_drill",
        "cloudflare",
        "kubernetes",
    ):
        assert forbidden not in source.lower()
