from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import socket
from datetime import datetime, timedelta, timezone
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
    scope_hash = digest(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode())
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
            "approvedRuleIdentitySha256": digest(IDENTITY),
            "approvedReviewer": "independent reviewer",
            "approvedScopeSha256": scope_hash,
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
            "maxFutureSkewSeconds": 0,
            "maxRehearsalWindowSeconds": 1800,
            "maxReviewWindowSeconds": 3600,
            "timeoutSeconds": 5,
            "retentionSeconds": 86400,
            "approvedAuthorizationLifetimeSeconds": 7200,
            "approvedEvidenceAgeSeconds": 1800,
            "approvedTimeoutSeconds": 5,
            "approvedRetentionSeconds": 86400,
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


def test_schema_version_must_be_an_integer_not_a_boolean():
    value = valid_input()
    value["schemaVersion"] = True
    with pytest.raises(planner.PlanError, match="schemaVersion"):
        build(value)


def test_schema_version_rejects_float():
    value = valid_input()
    value["schemaVersion"] = 1.0
    with pytest.raises(planner.PlanError, match="schemaVersion"):
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


@pytest.mark.parametrize(("identity", "configuration"), [(b"", CONFIGURATION), (IDENTITY, b"")])
def test_bound_local_files_must_not_be_empty(identity, configuration):
    value = valid_input()
    value["ruleAttestation"]["ruleIdentitySha256"] = digest(identity)
    value["ruleAttestation"]["reviewedConfigurationSha256"] = digest(configuration)
    with pytest.raises(planner.PlanError, match="must not be empty"):
        planner.build_plan(raw(value), identity, configuration, now=NOW)


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


def test_declared_evidence_one_second_in_the_future_is_rejected():
    value = valid_input()
    value["ruleAttestation"]["declaredAt"] = "2026-09-26T12:00:01Z"
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


@pytest.mark.parametrize("deadline", ["2026-09-26T11:59:59Z", "2026-09-26T12:25:00Z"])
def test_removal_deadline_must_be_future_dated_within_rehearsal(deadline):
    value = valid_input()
    value["authorization"]["removalDeadline"] = deadline
    with pytest.raises(planner.PlanError, match="future-dated within the rehearsal window"):
        build(value)


@pytest.mark.parametrize("field", ["rehearsalEndsAt", "reviewEndsAt", "expiresAt"])
def test_elapsed_lifecycle_deadlines_cannot_be_revived_by_later_expiry(field):
    value = valid_input()
    value["authorization"].update(
        {
            "rehearsalEndsAt": "2026-09-26T12:20:00Z",
            "reviewEndsAt": "2026-09-26T12:45:00Z",
            "removalDeadline": "2026-09-26T12:20:00Z",
            "expiresAt": "2026-09-26T13:00:00Z",
        }
    )
    validation_time = {
        "rehearsalEndsAt": datetime(2026, 9, 26, 12, 21, tzinfo=timezone.utc),
        "reviewEndsAt": datetime(2026, 9, 26, 12, 46, tzinfo=timezone.utc),
        "expiresAt": datetime(2026, 9, 26, 13, 1, tzinfo=timezone.utc),
    }[field]
    with pytest.raises(planner.PlanError):
        planner.build_plan(raw(value), IDENTITY, CONFIGURATION, now=validation_time)


@pytest.mark.parametrize("field", sorted(planner.POLICY_FIELDS - {"maxFutureSkewSeconds"}))
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
    ("field", "value", "message"),
    [
        ("maxFutureSkewSeconds", 1, "future evidence"),
        ("timeoutSeconds", 6, "timeout exceeds"),
        ("maxEvidenceAgeSeconds", 1801, "freshness exceeds"),
        ("retentionSeconds", 86401, "retention exceeds"),
        ("approvedAuthorizationLifetimeSeconds", 3899, "lifetime exceeds"),
    ],
)
def test_policy_values_must_fit_explicit_reviewed_bounds(field, value, message):
    document = valid_input()
    document["policy"][field] = value
    with pytest.raises(planner.PlanError, match=message):
        build(document)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("approvedRuleIdentitySha256", "sha256:" + "0" * 64),
        ("approvedReviewer", "different reviewer"),
        ("approvedScopeSha256", "sha256:" + "0" * 64),
    ],
)
def test_authorization_explicitly_binds_rule_reviewer_and_scope(field, replacement):
    value = valid_input()
    value["authorization"][field] = replacement
    with pytest.raises(planner.PlanError, match="authorization does not bind"):
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


@pytest.mark.parametrize(
    ("field", "secret"),
    [
        ("handoff", "Authorization Bearer FAKE_REVIEW_SENTINEL"),
        ("escalation", "Cookie session FAKE_REVIEW_SENTINEL"),
    ],
)
def test_named_fields_reject_credential_material(field, secret):
    value = valid_input()
    value["authorization"][field] = secret
    with pytest.raises(planner.PlanError):
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


def test_output_file_and_parent_directory_are_synced(tmp_path, monkeypatch):
    synced = []
    real_fsync = os.fsync

    def recording_fsync(descriptor):
        synced.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    planner.write_exclusive(tmp_path / "plan.json", build())
    assert len(synced) == 2


def test_output_descriptor_is_closed_if_fdopen_fails(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    closed = []
    real_close = os.close

    def failing_fdopen(*args, **kwargs):
        raise OSError("fdopen failed")

    def recording_close(descriptor):
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr(os, "fdopen", failing_fdopen)
    monkeypatch.setattr(os, "close", recording_close)
    with pytest.raises(OSError, match="fdopen failed"):
        planner.write_exclusive(path, build())
    assert len(closed) == 1
    assert not path.exists()


def test_output_is_removed_when_directory_sync_fails(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    calls = 0
    real_fsync = os.fsync

    def failing_directory_fsync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private filesystem detail")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", failing_directory_fsync)
    with pytest.raises(OSError):
        planner.write_exclusive(path, build())
    assert not path.exists()


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


def test_cli_requires_matching_lifecycle_and_local_files(tmp_path, monkeypatch):
    input_path = tmp_path / "input.json"
    identity_path = tmp_path / "identity"
    config_path = tmp_path / "configuration"
    output_path = tmp_path / "plan.json"
    value = valid_input()
    now = NOW
    timestamps = {
        "authorizedAt": now - timedelta(minutes=5),
        "rehearsalStartsAt": now - timedelta(minutes=1),
        "rehearsalEndsAt": now + timedelta(minutes=20),
        "reviewStartsAt": now - timedelta(minutes=1),
        "reviewEndsAt": now + timedelta(minutes=40),
        "removalDeadline": now + timedelta(minutes=20),
        "expiresAt": now + timedelta(hours=1),
    }
    value["authorization"].update(
        {field: timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") for field, timestamp in timestamps.items()}
    )
    value["ruleAttestation"]["declaredAt"] = (now - timedelta(minutes=4)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(planner, "datetime", FrozenDateTime)
    input_path.write_bytes(raw(value))
    identity_path.write_bytes(IDENTITY)
    config_path.write_bytes(CONFIGURATION)
    assert (
        planner.main(
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
        )
        == 0
    )
    assert json.loads(output_path.read_text())["networkCapable"] is False


def test_cli_rejects_non_object_authorization_without_traceback(tmp_path, capsys):
    input_path = tmp_path / "input.json"
    input_path.write_text('{"authorization":[]}')
    result = planner.main(
        [
            "--input",
            str(input_path),
            "--rule-identity",
            str(tmp_path / "unused-identity"),
            "--reviewed-configuration",
            str(tmp_path / "unused-configuration"),
            "--output",
            str(tmp_path / "plan.json"),
            "--lifecycle",
            "authorized-static-emulation",
        ]
    )
    assert result == 2
    diagnostics = capsys.readouterr().err
    assert "plan refused" in diagnostics
    assert "Traceback" not in diagnostics


@pytest.mark.parametrize("lifecycle", [None, "quota-exhaustion"])
def test_cli_rejects_missing_or_incorrect_lifecycle_without_output(tmp_path, capsys, lifecycle):
    input_path = tmp_path / "input.json"
    input_path.write_bytes(raw(valid_input()))
    identity_path = tmp_path / "identity"
    identity_path.write_bytes(IDENTITY)
    config_path = tmp_path / "configuration"
    config_path.write_bytes(CONFIGURATION)
    output_path = tmp_path / "plan.json"
    arguments = [
        "--input",
        str(input_path),
        "--rule-identity",
        str(identity_path),
        "--reviewed-configuration",
        str(config_path),
        "--output",
        str(output_path),
    ]
    if lifecycle is not None:
        arguments.extend(["--lifecycle", lifecycle])
    assert planner.main(arguments) == 2
    assert not output_path.exists()
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("authorization", [None, [], "bad", 1])
def test_cli_rejects_malformed_authorization_privately(tmp_path, capsys, authorization):
    sentinel = "FAKE_REVIEW_SENTINEL"
    input_path = tmp_path / sentinel
    input_path.write_text(json.dumps({"authorization": authorization}))
    output_path = tmp_path / "plan.json"
    result = planner.main(
        [
            "--input",
            str(input_path),
            "--rule-identity",
            str(tmp_path / "missing-rule"),
            "--reviewed-configuration",
            str(tmp_path / "missing-config"),
            "--output",
            str(output_path),
            "--lifecycle",
            "authorized-static-emulation",
        ]
    )
    diagnostics = capsys.readouterr().err
    assert result == 2
    assert not output_path.exists()
    assert sentinel not in diagnostics
    assert "Traceback" not in diagnostics


def test_duplicate_key_diagnostic_does_not_echo_attacker_input():
    sentinel = "FAKE_REVIEW_SENTINEL"
    with pytest.raises(planner.PlanError) as error:
        planner.load_input_bytes((f'{{"{sentinel}":1,"{sentinel}":2}}').encode())
    assert sentinel not in str(error.value)
