from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest

from scripts import tokenplace_static_429_observer as observer
from scripts import tokenplace_static_429_plan as planner
from tests.test_tokenplace_static_429_plan import CONFIGURATION, IDENTITY, NOW, raw, valid_input


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def plan_bytes() -> bytes:
    plan = planner.build_plan(raw(valid_input()), IDENTITY, CONFIGURATION, now=NOW)
    return json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()


def review(plan: bytes, **changes) -> bytes:
    value = {
        "schemaVersion": 1,
        "lifecycle": "authorized-static-emulation",
        "reviewer": "second plan reviewer",
        "decision": "approved",
        "declaredAt": "2026-09-26T12:00:00Z",
        "planSha256": digest(plan),
        "ruleIdentitySha256": digest(IDENTITY),
        "retentionSeconds": 86400,
        "retentionExpiresAt": "2026-09-27T12:00:00Z",
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


class FakeTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def __call__(self, **request):
        self.calls.append(request)
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def run(replies=(429, 429, 200, 200)):
    plan = plan_bytes()
    transport = FakeTransport(replies)
    return observer.observe(plan, review(plan), transport, now=NOW), transport


def test_exact_success_tuple_uses_one_shot_gets_and_plan_timeout():
    evidence, transport = run()
    assert evidence["outcome"] == "succeeded"
    assert evidence["statuses"] == {"/": 429, "/api/v1/meta": 429, "/livez": 200, "/healthz": 200}
    assert [call["url"] for call in transport.calls] == [
        "https://staging.token.place/",
        "https://staging.token.place/api/v1/meta",
        "https://staging.token.place/livez",
        "https://staging.token.place/healthz",
    ]
    assert all(call["method"] == "GET" for call in transport.calls)
    assert all(
        call["timeout"] == 5 and call["follow_redirects"] is False for call in transport.calls
    )
    assert evidence["quotaDrillEvidence"] is False
    assert evidence["originAttributed"] is False
    assert evidence["cleanup"]["state"] == "cleanup-pending"
    assert evidence["cleanup"]["observerPerformedRemoval"] is False


@pytest.mark.parametrize(
    ("replies", "attempts", "statuses"),
    [
        ((200,), 1, {"/": 200}),
        ((429, 200), 2, {"/": 429, "/api/v1/meta": 200}),
        ((429, 429, 429), 3, {"/": 429, "/api/v1/meta": 429, "/livez": 429}),
        ((429, 429, 200, 429), 4, {"/": 429, "/api/v1/meta": 429, "/livez": 200, "/healthz": 429}),
    ],
)
def test_unexpected_status_stops_without_retry_or_fabricated_statuses(replies, attempts, statuses):
    evidence, transport = run(replies)
    assert evidence["outcome"] == "failed"
    assert len(transport.calls) == attempts
    assert {
        key: value for key, value in evidence["statuses"].items() if value is not None
    } == statuses


@pytest.mark.parametrize("failure", [TimeoutError(), OSError("dns"), ConnectionError("tls")])
def test_transport_failures_are_redacted_and_one_shot(failure):
    evidence, transport = run((429, failure))
    assert evidence["diagnostic"] == "transport-failed"
    assert evidence["statuses"]["/"] == 429
    assert evidence["statuses"]["/api/v1/meta"] is None
    assert len(transport.calls) == 2
    assert "dns" not in json.dumps(evidence) and "tls" not in json.dumps(evidence)


@pytest.mark.parametrize(
    "reply", [{"status": 429, "redirected": True}, {"status": "429", "redirected": False}, object()]
)
def test_redirect_and_malformed_transport_response_fail_closed(reply):
    evidence, transport = run((reply,))
    assert evidence["outcome"] == "failed"
    assert len(transport.calls) == 1


def test_interruption_is_recorded_without_propagation_or_retry():
    evidence, transport = run((KeyboardInterrupt(),))
    assert evidence["diagnostic"] == "observation-interrupted"
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("lifecycle", "quota-exhaustion"),
        ("decision", "pending"),
        ("reviewer", "independent reviewer"),
        ("planSha256", "sha256:" + "0" * 64),
        ("ruleIdentitySha256", "sha256:" + "0" * 64),
        ("retentionSeconds", 1),
        ("retentionExpiresAt", "2026-09-27T12:00:01Z"),
    ],
)
def test_mismatched_review_declarations_are_rejected_before_transport(field, bad):
    plan = plan_bytes()
    transport = FakeTransport((429,))
    with pytest.raises(observer.ObserverError):
        observer.observe(plan, review(plan, **{field: bad}), transport, now=NOW)
    assert transport.calls == []


@pytest.mark.parametrize("declared", ["2026-09-26T12:00:01Z", "2026-09-26T10:00:00Z", "bad"])
def test_future_stale_and_malformed_review_is_rejected(declared):
    plan = plan_bytes()
    with pytest.raises(observer.ObserverError):
        observer.observe(plan, review(plan, declaredAt=declared), FakeTransport(()), now=NOW)


def test_duplicate_unknown_and_private_review_fields_are_rejected():
    plan = plan_bytes()
    good = review(plan)
    duplicate = good.replace(b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1')
    for bad in (duplicate, good[:-1] + b',"unknown":1}', good[:-1] + b',"cookie":"secret"}'):
        with pytest.raises(observer.ObserverError, match="review refused"):
            observer.observe(plan, bad, FakeTransport(()), now=NOW)


@pytest.mark.parametrize(
    ("section", "field", "bad"),
    [
        ("target", "authority", "token.place"),
        ("target", "authority", "user@staging.token.place"),
        ("target", "authority", "staging.token.place:443"),
        ("target", "authority", "staging.token.place?x=1"),
        ("target", "emulationPaths", ["/", "/api/v1/meta/"]),
        ("target", "method", "POST"),
        ("target", "followRedirects", True),
        (None, "expectedStatuses", {"/": 200}),
    ],
)
def test_drifted_target_url_method_and_status_contracts_are_rejected(section, field, bad):
    value = json.loads(plan_bytes())
    (value if section is None else value[section])[field] = bad
    changed = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(observer.ObserverError):
        observer.observe(changed, review(changed), FakeTransport(()), now=NOW)


def test_expired_plan_fails_before_transport():
    plan = plan_bytes()
    transport = FakeTransport(())
    with pytest.raises(observer.ObserverError, match="expired"):
        observer.observe(plan, review(plan), transport, now=NOW + timedelta(hours=2))
    assert not transport.calls


def test_abandonment_and_missed_deadline_always_signal_owner_cleanup():
    plan = plan_bytes()
    abandoned = observer.abandon(plan, now=NOW)
    assert abandoned["outcome"] == "abandoned"
    assert abandoned["cleanup"]["owner"] == "staging edge owner"
    late = observer.abandon(plan, now=NOW + timedelta(hours=1))
    assert late["cleanup"]["deadlineMissed"] is True
    assert late["cleanup"]["escalationRequired"] is True


def cleanup_bytes(evidence, **changes):
    value = {
        "schemaVersion": 1,
        "decision": "absent",
        "reviewer": "cleanup verifier",
        "declaredAt": "2026-09-26T12:01:00Z",
        "ruleIdentitySha256": evidence["ruleIdentitySha256"],
        "cleanupProofSha256": digest(b"privacy safe absence proof"),
        "ruleAbsent": True,
    }
    value.update(changes)
    return json.dumps(value, separators=(",", ":")).encode()


def test_fresh_identity_bound_cleanup_closes_only_cleanup_and_failure_is_immutable():
    evidence, _ = run((200,))
    cleaned = observer.apply_cleanup(
        evidence, cleanup_bytes(evidence), now=NOW + timedelta(minutes=2)
    )
    assert cleaned["cleanup"]["state"] == "cleanup-proven"
    assert cleaned["outcome"] == "failed"
    assert evidence["cleanup"]["state"] == "cleanup-pending"


@pytest.mark.parametrize(
    "changes",
    [
        {"ruleIdentitySha256": "sha256:" + "0" * 64},
        {"reviewer": "second plan reviewer"},
        {"reviewer": "independent reviewer"},
        {"declaredAt": "2026-09-26T12:03:00Z"},
        {"declaredAt": "2026-09-26T11:00:00Z"},
        {"ruleAbsent": False},
        {"cleanupProofSha256": "bad"},
    ],
)
def test_cleanup_proof_must_be_fresh_independent_and_identity_bound(changes):
    evidence, _ = run((200,))
    with pytest.raises(observer.ObserverError):
        observer.apply_cleanup(
            evidence, cleanup_bytes(evidence, **changes), now=NOW + timedelta(minutes=2)
        )


def test_plan_bytes_are_not_changed_and_evidence_has_no_sensitive_surface():
    plan = plan_bytes()
    before = bytes(plan)
    evidence = observer.observe(plan, review(plan), FakeTransport((429, 429, 200, 200)), now=NOW)
    assert plan == before
    encoded = json.dumps(evidence).lower()
    for forbidden in ("responsebody", "headers", "requestid", "cookie", "rawrule", "privateurl"):
        assert forbidden not in encoded


def test_module_has_no_mutation_clients_and_quota_runner_does_not_import_observer():
    source = open(observer.__file__, encoding="utf-8").read().lower()
    quota_source = open("scripts/tokenplace_incident_drill.py", encoding="utf-8").read().lower()
    for capability in ("import cloudflare", "import kubernetes", "kubectl", "import subprocess"):
        assert capability not in source
    assert "tokenplace_static_429_observer" not in quota_source
    assert "quotaDrillEvidence" not in evidence_keys_from_success()


def evidence_keys_from_success():
    evidence, _ = run()
    return {key for key, value in evidence.items() if value is True}
