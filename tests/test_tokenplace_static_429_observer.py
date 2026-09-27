from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import socket
import ssl
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


planner = load("static_429_planner_for_observer", ROOT / "scripts/tokenplace_static_429_plan.py")
observer = load(
    "tokenplace_static_429_observer", ROOT / "scripts/tokenplace_static_429_observer.py"
)
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
IDENTITY = b"opaque rule identity\n"
CONFIGURATION = b"opaque reviewed configuration\n"


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def plan_input():
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
            "approvedRuleIdentitySha256": digest(IDENTITY),
            "approvedReviewer": "rule reviewer",
            "approvedScopeSha256": digest(
                json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()
            ),
        },
        "ruleAttestation": {
            "reviewer": "rule reviewer",
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


def plan_bytes():
    source = json.dumps(plan_input(), separators=(",", ":")).encode()
    plan = planner.build_plan(source, IDENTITY, CONFIGURATION, now=NOW)
    return json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()


def review_bytes(plan_raw=None, **changes):
    plan_raw = plan_raw or plan_bytes()
    value = {
        "schemaVersion": 1,
        "decision": "approved",
        "reviewer": "second reviewer",
        "declaredAt": "2026-09-26T11:59:00Z",
        "planSha256": digest(plan_raw),
        "retentionSeconds": 86400,
        "retentionEndsAt": "2026-09-27T11:59:00Z",
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


class FakeTransport:
    def __init__(self, values=(429, 429, 200, 200)):
        self.values = iter(values)
        self.calls = []

    def __call__(self, method, url, timeout, follow_redirects):
        self.calls.append((method, url, timeout, follow_redirects))
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, observer.TransportResult):
            return value
        return observer.TransportResult(value)


def run(transport=None, raw_plan=None, raw_review=None, **kwargs):
    raw_plan = raw_plan or plan_bytes()
    return observer.observe(
        raw_plan,
        raw_review or review_bytes(raw_plan),
        transport or FakeTransport(),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def test_exact_tuple_makes_four_one_shot_gets_and_emits_cleanup_signal():
    transport = FakeTransport()
    result = run(transport)
    assert result["outcome"] == "success"
    assert [item["status"] for item in result["routes"]] == [429, 429, 200, 200]
    assert transport.calls == [
        ("GET", f"https://staging.token.place{path}", 5, False) for path in observer.ROUTES
    ]
    assert result["cleanup"] == {
        "required": True,
        "state": "cleanup-pending",
        "ruleIdentitySha256": digest(IDENTITY),
        "owner": "staging edge owner",
        "deadline": "2026-09-26T12:20:00Z",
        "escalation": "staging incident channel",
        "deadlineMissed": False,
        "ownerMustRemoveImmediately": True,
        "observerPerformedRemoval": False,
    }
    assert result["quotaDrillEvidence"] is result["originAttributed"] is False


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("status", [199, 201, 301, 404, 500])
def test_every_unexpected_status_stops_once_without_fabricating_routes(index, status):
    values = list(observer.EXPECTED)
    values[index] = status
    transport = FakeTransport(values)
    with pytest.raises(observer.ObserverError) as caught:
        run(transport)
    evidence = caught.value.evidence
    assert len(transport.calls) == index + 1
    assert [item["observed"] for item in evidence["routes"]] == [
        route <= index for route in range(4)
    ]
    assert all(item["status"] is None for item in evidence["routes"][index + 1 :])
    assert evidence["outcome"] == "failed"
    assert evidence["cleanup"]["state"] == "cleanup-pending"


def test_redirect_flag_is_rejected_even_with_expected_integer_status():
    transport = FakeTransport([observer.TransportResult(429, True)])
    with pytest.raises(observer.ObserverError, match="redirect"):
        run(transport)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (TimeoutError(), "timeout"),
        (socket.timeout(), "timeout"),
        (ssl.SSLError(), "transport-failure"),
        (socket.gaierror(), "transport-failure"),
        (OSError(), "transport-failure"),
        (KeyboardInterrupt(), "interrupted"),
    ],
)
def test_transport_timeout_tls_dns_and_interruption_are_fixed_and_one_shot(failure, code):
    transport = FakeTransport([failure])
    with pytest.raises(observer.ObserverError) as caught:
        run(transport)
    assert caught.value.code == code
    assert len(transport.calls) == 1
    assert all(not route["observed"] for route in caught.value.evidence["routes"])


@pytest.mark.parametrize(
    ("section", "field", "replacement"),
    [
        ("target", "scheme", "http"),
        ("target", "authority", "token.place"),
        ("target", "authority", "user@staging.token.place"),
        ("target", "authority", "staging.token.place:443"),
        ("target", "authority", "staging.token.place?x=1"),
        ("target", "authority", "staging.token.place#x"),
        ("target", "method", "POST"),
        ("target", "emulationPaths", ["/", "/api/v1/meta/"]),
        ("target", "followRedirects", True),
        ("authorization", "lifecycle", "quota-exhaustion"),
    ],
)
def test_plan_target_and_lifecycle_drift_fail_before_transport(section, field, replacement):
    plan = json.loads(plan_bytes())
    plan[section][field] = replacement
    transport = FakeTransport()
    with pytest.raises(observer.ObserverError):
        run(transport, json.dumps(plan).encode())
    assert transport.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewer": "rule reviewer"},
        {"planSha256": "sha256:" + "0" * 64},
        {"retentionSeconds": 1},
        {"declaredAt": "2026-09-26T12:00:01Z"},
        {"declaredAt": "2026-09-26T11:20:00Z"},
        {"decision": "pending"},
    ],
)
def test_second_review_must_be_fresh_distinct_and_bound(changes):
    raw_plan = plan_bytes()
    transport = FakeTransport()
    with pytest.raises(observer.ObserverError) as caught:
        run(transport, raw_plan, review_bytes(raw_plan, **changes))
    assert transport.calls == []
    assert caught.value.evidence["cleanup"]["state"] == "cleanup-pending"


def test_expired_and_not_yet_active_plans_fail_with_never_started_cleanup():
    for current, code in [
        (NOW - timedelta(seconds=1), "plan-not-active"),
        (NOW + timedelta(minutes=21), "plan-expired"),
    ]:
        raw_plan = plan_bytes()
        review_time = (current - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        retention_end = (current - timedelta(seconds=1) + timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        review = review_bytes(raw_plan, declaredAt=review_time, retentionEndsAt=retention_end)
        with pytest.raises(observer.ObserverError) as caught:
            run(FakeTransport(), raw_plan, review, now=current)
        assert caught.value.code == code
        assert caught.value.evidence["reason"] == "not-started"
        assert not any(route["observed"] for route in caught.value.evidence["routes"])


def test_abandonment_before_observation_requires_cleanup():
    transport = FakeTransport()
    with pytest.raises(observer.ObserverError) as caught:
        run(transport, abandon=True)
    assert caught.value.code == "abandoned"
    assert caught.value.evidence["cleanup"]["required"] is True
    assert transport.calls == []


def cleanup_bytes(evidence, **changes):
    value = {
        "schemaVersion": 1,
        "decision": "absent",
        "reviewer": "cleanup reviewer",
        "declaredAt": "2026-09-26T12:01:00Z",
        "ruleIdentitySha256": evidence["ruleIdentitySha256"],
        "observationSha256": observer.observation_digest(evidence),
        "absenceProofSha256": digest(b"privacy-safe absence proof"),
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def test_identity_bound_cleanup_closes_obligation_without_changing_failed_outcome():
    with pytest.raises(observer.ObserverError) as caught:
        run(FakeTransport([500]))
    failed = caught.value.evidence
    cleaned = observer.apply_cleanup(failed, cleanup_bytes(failed), now=NOW + timedelta(minutes=2))
    assert cleaned["cleanup"]["state"] == "cleanup-proven"
    assert cleaned["outcome"] == "failed"
    assert failed["cleanup"]["state"] == "cleanup-pending"


@pytest.mark.parametrize(
    "changes",
    [
        {"ruleIdentitySha256": "sha256:" + "0" * 64},
        {"observationSha256": "sha256:" + "0" * 64},
        {"declaredAt": "2026-09-26T11:59:00Z"},
        {"reviewer": "staging edge owner"},
        {"reviewer": "rule reviewer"},
        {"reviewer": "second reviewer"},
        {"declaredAt": "2026-09-26T12:01:00Z"},
        {"absenceProofSha256": "not-a-hash"},
    ],
)
def test_cleanup_proof_must_be_fresh_independent_and_bound(changes):
    evidence = run()
    cleanup_now = (
        NOW + timedelta(hours=1)
        if changes.get("declaredAt") == "2026-09-26T12:01:00Z"
        else NOW + timedelta(minutes=2)
    )
    with pytest.raises(observer.ObserverError):
        observer.apply_cleanup(evidence, cleanup_bytes(evidence, **changes), now=cleanup_now)
    assert evidence["cleanup"]["state"] == "cleanup-pending"


def test_missed_deadline_uses_declared_escalation():
    raw_plan = plan_bytes()
    plan = json.loads(raw_plan)
    evidence = observer._initial_evidence(plan, raw_plan, NOW + timedelta(minutes=21))
    assert evidence["cleanup"]["deadlineMissed"] is True
    assert evidence["cleanup"]["escalation"] == "staging incident channel"


@pytest.mark.parametrize("document", [b"{}", b"[]", b'{"schemaVersion":1,"schemaVersion":1}'])
def test_malformed_duplicate_or_unknown_review_schema_fails_closed(document):
    with pytest.raises(observer.ObserverError) as caught:
        run(FakeTransport(), raw_review=document)
    assert "FAKE" not in str(caught.value)


@pytest.mark.parametrize(
    "field", ["cookie", "responseBody", "request_id", "rawRule", "privateURL", "errors"]
)
def test_privacy_fields_never_enter_evidence_or_diagnostics(field):
    sentinel = "FAKE_PRIVATE_SENTINEL"
    review = json.loads(review_bytes())
    review[field] = sentinel
    with pytest.raises(observer.ObserverError) as caught:
        run(FakeTransport(), raw_review=json.dumps(review).encode())
    rendered = str(caught.value) + json.dumps(caught.value.evidence)
    assert sentinel not in rendered


def test_planner_bytes_are_not_changed_and_no_live_network_is_used(monkeypatch):
    raw_plan = plan_bytes()
    before = bytes(raw_plan)
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: pytest.fail("live network"))
    run(FakeTransport(), raw_plan)
    assert raw_plan == before


def test_observer_has_no_mutation_or_quota_runner_surface():
    source = (ROOT / "scripts/tokenplace_static_429_observer.py").read_text()
    quota_source = (ROOT / "scripts/tokenplace_incident_drill.py").read_text()
    assert "tokenplace_static_429_observer" not in quota_source
    assert "tokenplace_incident_drill" not in source
    assert all(
        word not in source.lower()
        for word in ("cloudflare", "kubernetes", "servicemonitor", "deployment", "registry")
    )
    assert run()["quotaDrillEvidence"] is False
