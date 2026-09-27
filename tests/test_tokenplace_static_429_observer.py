from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


planner = load("tokenplace_static_429_plan")
observer = load("tokenplace_static_429_observer")
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
IDENTITY = b"opaque identity"
CONFIGURATION = b"opaque configuration"


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def inputs():
    scope = {
        "scheme": "https",
        "authority": "staging.token.place",
        "method": "GET",
        "emulationPaths": ["/", "/api/v1/meta"],
        "healthControlPaths": ["/livez", "/healthz"],
        "followRedirects": False,
    }
    scope_hash = digest(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode())
    value = {
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
            "removalOwner": "edge owner",
            "handoff": "operations handoff",
            "escalation": "incident channel",
            "approvedRuleIdentitySha256": digest(IDENTITY),
            "approvedReviewer": "scope reviewer",
            "approvedScopeSha256": scope_hash,
        },
        "ruleAttestation": {
            "reviewer": "scope reviewer",
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
    source = json.dumps(value, separators=(",", ":")).encode()
    plan = planner.build_plan(source, IDENTITY, CONFIGURATION, now=NOW)
    plan_raw = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    review = {
        "schemaVersion": 1,
        "reviewer": "plan reviewer",
        "decision": "approved",
        "declaredAt": "2026-09-26T11:58:00Z",
        "planSha256": digest(plan_raw),
        "retentionSeconds": 86400,
        "retentionEndsAt": "2026-09-27T11:58:00Z",
    }
    return plan_raw, json.dumps(review, separators=(",", ":")).encode()


class Response:
    def __init__(self, status, redirected=False):
        self.status = status
        self.redirected = redirected


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        return value


def test_exact_tuple_is_observed_once_offline_and_cleanup_is_immediate():
    plan, review = inputs()
    transport = FakeTransport([Response(429), Response(429), Response(200), Response(200)])
    result = observer.observe(plan, review, transport, now=NOW)
    assert result["outcome"] == "success"
    assert [item["status"] for item in result["observations"]] == [429, 429, 200, 200]
    assert [call["url"] for call in transport.calls] == [
        f"https://staging.token.place{x}" for x in observer.ROUTES
    ]
    assert all(
        call["method"] == "GET" and call["timeout"] == 5 and call["follow_redirects"] is False
        for call in transport.calls
    )
    assert result["cleanupState"] == "cleanup-pending"
    assert result["cleanupRequired"]["performedByObserver"] is False
    assert result["quotaDrillEvidence"] is result["originAttributed"] is False


@pytest.mark.parametrize("responses", [[500], [Response(302, True)], [429, 200], [429, 429, 503]])
def test_unexpected_status_or_redirect_stops_without_retry(responses):
    plan, review = inputs()
    transport = FakeTransport(responses)
    result = observer.observe(plan, review, transport, now=NOW)
    assert result["outcome"] == "failed"
    assert len(transport.calls) == len(responses)
    assert sum(item["observed"] for item in result["observations"]) == len(responses)
    assert all(item["status"] is None for item in result["observations"][len(responses) :])


@pytest.mark.parametrize(
    "failure", [TimeoutError(), OSError("tls"), ConnectionError("dns"), RuntimeError("transport")]
)
def test_transport_failures_are_redacted_and_not_retried(failure):
    plan, review = inputs()
    transport = FakeTransport([failure])
    result = observer.observe(plan, review, transport, now=NOW)
    assert len(transport.calls) == 1
    assert result["diagnostic"] == "transport-failure"
    if str(failure):
        assert str(failure) not in json.dumps(result).replace("transport-failure", "")


def test_interrupt_and_abandonment_preserve_unobserved_routes():
    plan, review = inputs()
    interrupted = observer.observe(plan, review, FakeTransport([KeyboardInterrupt()]), now=NOW)
    abandoned = observer.abandon(plan, review, now=NOW)
    assert interrupted["diagnostic"] == "observation-interrupted"
    assert all(not row["observed"] and row["status"] is None for row in abandoned["observations"])
    assert abandoned["outcome"] == interrupted["outcome"] == "failed"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p, r: p["target"].update(authority="token.place"),
        lambda p, r: p["target"].update(authority="user@staging.token.place"),
        lambda p, r: p["target"].update(authority="staging.token.place:443"),
        lambda p, r: p["target"].update(emulationPaths=["/", "/api/v1/meta/"]),
        lambda p, r: p["target"].update(method="POST"),
        lambda p, r: p["target"].update(followRedirects=True),
        lambda p, r: p.update(unexpected=True),
        lambda p, r: r.update(unexpected=True),
        lambda p, r: r.update(planSha256="sha256:" + "0" * 64),
        lambda p, r: r.update(reviewer="scope reviewer"),
        lambda p, r: r.update(retentionSeconds=1),
    ],
)
def test_drift_mismatch_and_unknown_fields_fail_before_transport(mutation):
    plan_raw, review_raw = inputs()
    plan, review = json.loads(plan_raw), json.loads(review_raw)
    mutation(plan, review)
    transport = FakeTransport([429])
    with pytest.raises(observer.ObserverError):
        observer.observe(json.dumps(plan).encode(), json.dumps(review).encode(), transport, now=NOW)
    assert transport.calls == []


def test_duplicate_and_privacy_fields_fail_closed():
    plan, review = inputs()
    duplicate = review.replace(b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1')
    with pytest.raises(observer.ObserverError, match="duplicate"):
        observer.observe(plan, duplicate, FakeTransport([]), now=NOW)
    unsafe = json.loads(review)
    unsafe["responseBody"] = "secret"
    with pytest.raises(observer.ObserverError, match="privacy"):
        observer.observe(plan, json.dumps(unsafe).encode(), FakeTransport([]), now=NOW)


@pytest.mark.parametrize("when", [NOW - timedelta(seconds=1801), NOW + timedelta(seconds=1)])
def test_stale_and_future_second_review_are_rejected(when):
    plan, review_raw = inputs()
    review = json.loads(review_raw)
    review["declaredAt"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    review["retentionEndsAt"] = (when + timedelta(seconds=86400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(observer.ObserverError):
        observer.observe(plan, json.dumps(review).encode(), FakeTransport([]), now=NOW)


def test_expired_plan_is_rejected_without_a_request():
    plan, review = inputs()
    transport = FakeTransport([])
    with pytest.raises(observer.ObserverError, match="expired"):
        observer.observe(plan, review, transport, now=NOW + timedelta(minutes=21))
    assert transport.calls == []


def test_cleanup_is_identity_bound_independent_and_failure_is_immutable():
    plan, review = inputs()
    record = observer.observe(plan, review, FakeTransport([500]), now=NOW)
    proof = b"bounded absence proof"
    declaration = {
        "schemaVersion": 1,
        "reviewer": "cleanup reviewer",
        "decision": "rule-absent",
        "declaredAt": "2026-09-26T12:01:00Z",
        "ruleIdentitySha256": record["ruleIdentitySha256"],
        "cleanupProofSha256": digest(proof),
    }
    updated = observer.apply_cleanup(
        record, json.dumps(declaration).encode(), proof, now=NOW + timedelta(minutes=2)
    )
    assert updated["cleanupState"] == "cleanup-proven"
    assert updated["outcome"] == "failed"
    declaration["ruleIdentitySha256"] = "sha256:" + "0" * 64
    with pytest.raises(observer.ObserverError, match="identity"):
        observer.apply_cleanup(
            record, json.dumps(declaration).encode(), proof, now=NOW + timedelta(minutes=2)
        )


def test_missed_cleanup_deadline_requires_escalation():
    plan_raw, review = inputs()
    plan = json.loads(plan_raw)
    signal = observer._cleanup_signal(plan, NOW + timedelta(minutes=21))
    assert signal["deadlineMissed"] is signal["escalationRequired"] is True


def test_module_has_no_mutation_or_default_network_capability_and_quota_runner_is_unchanged():
    source = (ROOT / "scripts/tokenplace_static_429_observer.py").read_text()
    quota_source = (ROOT / "scripts/tokenplace_incident_drill.py").read_text()
    forbidden = (
        "cloudflare",
        "kubernetes",
        "servicemonitor",
        "deployment",
        "registry",
        "subprocess",
        "requests",
        "urllib",
    )
    assert all(word not in source.lower() for word in forbidden)
    assert "tokenplace_static_429_observer" not in quota_source
    assert (
        'statuses != {"root": 200, "metadata": 200, "livez": 200, "healthz": 200}' in quota_source
    )


def test_plan_bytes_are_not_modified():
    plan, review = inputs()
    before = bytes(plan)
    observer.observe(plan, review, FakeTransport([429, 429, 200, 200]), now=NOW)
    assert plan == before
