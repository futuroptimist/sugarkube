import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "tokenplace_static_429_plan.py"
SPEC = importlib.util.spec_from_file_location("static_plan", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_input():
    return {
        "schema_version": 1,
        "lifecycle": "authorized-static-emulation",
        "target": {
            "scheme": "https",
            "authority": "staging.token.place",
            "routes": [
                {"method": "GET", "path": "/", "role": "emulation", "expected_status": 429},
                {
                    "method": "GET",
                    "path": "/api/v1/meta",
                    "role": "emulation",
                    "expected_status": 429,
                },
                {
                    "method": "GET",
                    "path": "/livez",
                    "role": "health-control",
                    "expected_status": 200,
                },
                {
                    "method": "GET",
                    "path": "/healthz",
                    "role": "health-control",
                    "expected_status": 200,
                },
            ],
            "redirect_policy": "reject",
        },
        "authorization": {
            "reviewer": "staging reviewer",
            "decision": "approved",
            "decided_at": "2026-09-26T11:55:00Z",
            "rehearsal_start": "2026-09-26T11:50:00Z",
            "rehearsal_end": "2026-09-26T13:00:00Z",
            "review_start": "2026-09-26T12:00:00Z",
            "review_end": "2026-09-26T12:45:00Z",
            "expires_at": "2026-09-26T12:30:00Z",
            "removal_deadline": "2026-09-26T12:40:00Z",
            "removal_owner": "edge owner",
            "handoff": "notify the edge owner immediately",
            "escalation": "open the staging incident path",
        },
        "rule_scope_attestation": {
            "reviewer": "scope reviewer",
            "decision": "scope-approved",
            "attested_at": "2026-09-26T11:56:00Z",
            "authority": "staging.token.place",
            "methods": ["GET"],
            "emulated_paths": ["/", "/api/v1/meta"],
            "rule_identity_sha256": "a" * 64,
            "reviewed_configuration_sha256": "b" * 64,
        },
        "policy": {
            "validation_time": "2026-09-26T12:00:00Z",
            "freshness_seconds": 600,
            "retention_seconds": 86400,
            "timeout_seconds": 5,
        },
    }


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def test_valid_plan_is_deterministic_byte_bound_and_offline(tmp_path):
    raw = encode(valid_input())
    first = MODULE.parse_and_validate(raw)
    second = MODULE.parse_and_validate(raw)
    assert first == second
    assert first["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert first["target"]["routes"] == valid_input()["target"]["routes"]
    assert first["capabilities"] == {"network": False, "mutation": False, "quota_stimulus": False}
    assert (
        "claim" in first["claim_notice"].lower() or "declaration" in first["claim_notice"].lower()
    )
    output = tmp_path / "plan.json"
    MODULE.write_exclusive(output, first)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        MODULE.write_exclusive(output, first)
    assert output.read_bytes() == original


@pytest.mark.parametrize("lifecycle", [None, "quota-exhaustion", "authorized-static-emulation "])
def test_requires_exact_opt_in(lifecycle):
    value = valid_input()
    if lifecycle is None:
        del value["lifecycle"]
    else:
        value["lifecycle"] = lifecycle
    with pytest.raises(MODULE.PlanError):
        MODULE.parse_and_validate(encode(value))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("authority", "token.place"),
        ("authority", "staging.token.place:443"),
        ("authority", "user@staging.token.place"),
        ("scheme", "http"),
        ("redirect_policy", "follow"),
    ],
)
def test_rejects_noncanonical_target(field, replacement):
    value = valid_input()
    value["target"][field] = replacement
    with pytest.raises(MODULE.PlanError):
        MODULE.parse_and_validate(encode(value))


@pytest.mark.parametrize("path", ["//", "/./", "/?x=1", "/#fragment", "/livez/"])
def test_rejects_path_variants(path):
    value = valid_input()
    value["target"]["routes"][0]["path"] = path
    with pytest.raises(MODULE.PlanError):
        MODULE.parse_and_validate(encode(value))


def test_rejects_broad_or_changed_scope_and_hashes():
    for mutate in (
        lambda value: value["rule_scope_attestation"]["emulated_paths"].append("/healthz"),
        lambda value: value["rule_scope_attestation"].__setitem__("methods", ["GET", "POST"]),
        lambda value: value["rule_scope_attestation"].__setitem__("rule_identity_sha256", "A" * 64),
    ):
        value = valid_input()
        mutate(value)
        with pytest.raises(MODULE.PlanError):
            MODULE.parse_and_validate(encode(value))


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("authorization", "decided_at", "2026-09-26T12:01:00Z"),
        ("authorization", "decided_at", "2026-09-26T11:00:00Z"),
        ("authorization", "rehearsal_end", "2026-09-26T11:59:59Z"),
        ("authorization", "review_end", "2026-09-26T13:01:00Z"),
        ("authorization", "expires_at", "2026-09-26T12:00:00Z"),
        ("authorization", "removal_deadline", "not-a-time"),
        ("policy", "timeout_seconds", 0),
    ],
)
def test_rejects_invalid_time_and_policy_bounds(section, field, replacement):
    value = valid_input()
    value[section][field] = replacement
    with pytest.raises(MODULE.PlanError):
        MODULE.parse_and_validate(encode(value))


def test_rejects_unknown_duplicate_and_privacy_fields():
    value = valid_input()
    value["unknown"] = True
    with pytest.raises(MODULE.PlanError):
        MODULE.parse_and_validate(encode(value))
    with pytest.raises(MODULE.PlanError, match="duplicate"):
        MODULE.parse_and_validate(b'{"schema_version":1,"schema_version":1}')
    value = valid_input()
    value["authorization"]["cookie"] = "secret"
    with pytest.raises(MODULE.PlanError, match="privacy"):
        MODULE.parse_and_validate(encode(value))


def test_source_has_no_network_or_live_executor_capability():
    source = SCRIPT.read_text()
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
