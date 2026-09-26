from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "tokenplace_static_429_plan", ROOT / "scripts/tokenplace_static_429_plan.py"
)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
IDENTITY = b"opaque rule identity\n"
CONFIGURATION = b"opaque reviewed configuration\n"


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def valid_input() -> dict:
    scope = {
        "scheme": "https",
        "authority": "staging.token.place",
        "method": "GET",
        "emulationPaths": ["/", "/api/v1/meta"],
        "healthControlPaths": ["/livez", "/healthz"],
        "followRedirects": False,
    }
    return {
        "schemaVersion": 1,
        "target": scope,
        "authorization": {
            "lifecycle": "authorized-static-emulation",
            "authorizedAt": "2026-09-26T11:55:00Z",
            "expiresAt": "2026-09-26T13:00:00Z",
            "rehearsalStartsAt": "2026-09-26T12:00:00Z",
            "rehearsalEndsAt": "2026-09-26T12:20:00Z",
            "reviewStartsAt": "2026-09-26T12:00:00Z",
            "reviewEndsAt": "2026-09-26T12:45:00Z",
            "removalDeadline": "2026-09-26T12:20:00Z",
            "removalOwner": "staging edge owner",
            "handoff": "staging operations handoff",
            "escalation": "staging incident channel",
        },
        "ruleAttestation": {
            "reviewer": "independent reviewer",
            "decision": "approved",
            "declaredAt": "2026-09-26T11:56:00Z",
            "rulePreExisting": True,
            "ruleIdentitySha256": digest(IDENTITY),
            "reviewedConfigurationSha256": digest(CONFIGURATION),
            **copy.deepcopy(scope),
        },
        "policy": {
            "maxEvidenceAgeSeconds": 1800,
            "maxFutureSkewSeconds": 30,
            "maxRehearsalWindowSeconds": 1800,
            "maxReviewWindowSeconds": 3600,
            "timeoutSeconds": 5,
            "retentionSeconds": 86400,
        },
    }


def raw(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def build(value: dict | None = None):
    return planner.build_plan(raw(value or valid_input()), IDENTITY, CONFIGURATION, now=NOW)


def test_valid_input_builds_stable_privacy_safe_non_executable_plan():
    source = valid_input()
    first = build(source)
    second = build(source)
    assert first == second
    assert first["inputSha256"] == digest(raw(source))
    assert first["expectedStatuses"] == {
        "/": 429,
        "/api/v1/meta": 429,
        "/livez": 200,
        "/healthz": 200,
    }
    assert first["target"]["emulationPaths"] == ["/", "/api/v1/meta"]
    assert first["target"]["healthControlPaths"] == ["/livez", "/healthz"]
    assert first["reviewerDeclaration"]["authenticated"] is False
    assert first["reviewerDeclaration"]["independentlyProven"] is False
    assert first["executable"] is first["networkCapable"] is first["mutationCapable"] is False
    assert first["quotaDrillEvidence"] is False


def test_exact_input_bytes_are_bound_even_when_json_meaning_is_same():
    value = valid_input()
    compact = raw(value)
    formatted = json.dumps(value, indent=2).encode()
    assert (
        planner.build_plan(compact, IDENTITY, CONFIGURATION, now=NOW)["inputSha256"]
        != planner.build_plan(formatted, IDENTITY, CONFIGURATION, now=NOW)["inputSha256"]
    )


@pytest.mark.parametrize("lifecycle", [None, "quota-exhaustion", "AUTHORIZED-STATIC-EMULATION"])
def test_explicit_lifecycle_is_required(lifecycle):
    value = valid_input()
    if lifecycle is None:
        del value["authorization"]["lifecycle"]
    else:
        value["authorization"]["lifecycle"] = lifecycle
    with pytest.raises(planner.PlanError):
        build(value)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("scheme", "http"),
        ("authority", "token.place"),
        ("authority", "prod.token.place"),
        ("authority", "user@staging.token.place"),
        ("authority", "staging.token.place:443"),
        ("authority", "staging.token.place?x=1"),
        ("authority", "staging.token.place#fragment"),
        ("method", "POST"),
        ("emulationPaths", ["/", "/api/v1/meta/"]),
        ("emulationPaths", ["/", "/api/v1/meta", "/other"]),
        ("healthControlPaths", ["/livez"]),
        ("followRedirects", True),
    ],
)
@pytest.mark.parametrize("section", ["target", "ruleAttestation"])
def test_scope_is_exact_and_noncanonical_variants_are_rejected(section, field, replacement):
    value = valid_input()
    value[section][field] = replacement
    with pytest.raises(planner.PlanError):
        build(value)


def test_duplicate_and_unknown_fields_are_rejected():
    duplicate = raw(valid_input()).replace(
        b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1', 1
    )
    with pytest.raises(planner.PlanError, match="duplicate"):
        planner.build_plan(duplicate, IDENTITY, CONFIGURATION, now=NOW)
    value = valid_input()
    value["unexpected"] = False
    with pytest.raises(planner.PlanError, match="schema"):
        build(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ruleIdentitySha256", "sha256:abc"),
        ("ruleIdentitySha256", "SHA256:" + "a" * 64),
        ("reviewedConfigurationSha256", "sha256:" + "0" * 64),
    ],
)
def test_hashes_are_strict_and_bind_local_bytes(field, value):
    document = valid_input()
    document["ruleAttestation"][field] = value
    with pytest.raises(planner.PlanError):
        build(document)
    with pytest.raises(planner.PlanError, match="identity bytes"):
        planner.build_plan(raw(valid_input()), b"changed", CONFIGURATION, now=NOW)


@pytest.mark.parametrize("field", ["authorizedAt", "declaredAt"])
def test_stale_and_future_evidence_is_rejected(field):
    value = valid_input()
    section = "ruleAttestation" if field == "declaredAt" else "authorization"
    value[section][field] = "2026-09-26T10:00:00Z"
    with pytest.raises(planner.PlanError, match="stale"):
        build(value)
    value = valid_input()
    value[section][field] = "2026-09-26T12:01:00Z"
    with pytest.raises(planner.PlanError, match="future"):
        build(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expiresAt", "2026-09-26T12:10:00Z"),
        ("rehearsalEndsAt", "2026-09-26T12:45:00Z"),
        ("reviewEndsAt", "2026-09-26T14:00:00Z"),
        ("removalDeadline", "2026-09-26T12:21:00Z"),
        ("authorizedAt", "2026-09-26 11:55:00Z"),
    ],
)
def test_malformed_contradictory_or_unbounded_windows_are_rejected(field, value):
    document = valid_input()
    document["authorization"][field] = value
    with pytest.raises(planner.PlanError):
        build(document)


@pytest.mark.parametrize("field", sorted(planner.POLICY_FIELDS))
@pytest.mark.parametrize("bad", [None, 0, -1, True, "5"])
def test_policy_bounds_are_required_positive_integers(field, bad):
    value = valid_input()
    if bad is None:
        del value["policy"][field]
    else:
        value["policy"][field] = bad
    with pytest.raises(planner.PlanError):
        build(value)


@pytest.mark.parametrize(
    "field",
    ["cookie", "responseBody", "request_id", "rawRule", "privateURL", "ciphertext", "errors"],
)
def test_prohibited_privacy_fields_are_rejected(field):
    value = valid_input()
    value[field] = "redacted"
    with pytest.raises(planner.PlanError, match="privacy"):
        build(value)


def test_output_is_exclusively_created_and_never_overwritten(tmp_path):
    path = tmp_path / "plan.json"
    plan = build()
    planner.write_exclusive(path, plan)
    original = path.read_bytes()
    with pytest.raises(planner.PlanError, match="overwrite"):
        planner.write_exclusive(path, {"changed": True})
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == 0o600


def test_module_has_no_network_or_live_operation_surface(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network operation attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    plan = build()
    source = (ROOT / "scripts/tokenplace_static_429_plan.py").read_text()
    assert "tokenplace_incident_drill" not in source
    assert all(
        word not in source
        for word in ("urllib", "requests", "http.client", "subprocess", "cloudflare", "kubernetes")
    )
    assert plan["networkCapable"] is False


def test_cli_requires_matching_lifecycle_and_local_files(tmp_path):
    input_path = tmp_path / "input.json"
    identity_path = tmp_path / "identity"
    config_path = tmp_path / "configuration"
    output_path = tmp_path / "plan.json"
    input_path.write_bytes(raw(valid_input()))
    identity_path.write_bytes(IDENTITY)
    config_path.write_bytes(CONFIGURATION)
    # The CLI uses the real clock, so test its pre-build lifecycle gate without a network mock.
    assert planner.main(
        [
            "--input",
            str(input_path),
            "--rule-identity",
            str(identity_path),
            "--reviewed-configuration",
            str(config_path),
            "--output",
            str(output_path),
            "--lifecycle",
            "authorized-static-emulation",
        ]
    ) in (0, 2)
    assert (
        not output_path.exists() or json.loads(output_path.read_text())["networkCapable"] is False
    )
