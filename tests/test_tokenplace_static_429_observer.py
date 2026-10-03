from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from test_tokenplace_static_429_plan import CONFIGURATION, IDENTITY, valid_input  # noqa: E402

PLAN_SPEC = importlib.util.spec_from_file_location(
    "tokenplace_static_429_plan", ROOT / "scripts/tokenplace_static_429_plan.py"
)
assert PLAN_SPEC and PLAN_SPEC.loader
planner = importlib.util.module_from_spec(PLAN_SPEC)
PLAN_SPEC.loader.exec_module(planner)
SPEC = importlib.util.spec_from_file_location(
    "tokenplace_static_429_observer", ROOT / "scripts/tokenplace_static_429_observer.py"
)
assert SPEC and SPEC.loader
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)
NOW = datetime(2026, 9, 26, 12, 5, tzinfo=timezone.utc)


def encoded(value) -> bytes:  # noqa: ANN001
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def plan_bytes() -> bytes:
    value = planner.build_plan(
        json.dumps(valid_input(), separators=(",", ":")).encode(),
        IDENTITY,
        CONFIGURATION,
        now=NOW,
    )
    return encoded(value)


def review(plan: bytes, **updates) -> bytes:  # noqa: ANN003
    value = {
        "schemaVersion": 1,
        "lifecycle": "authorized-static-emulation",
        "reviewer": "second reviewer",
        "decision": "approved",
        "declaredAt": "2026-09-26T12:04:00Z",
        "planSha256": digest(plan),
        "ruleIdentitySha256": digest(IDENTITY),
        "retentionSeconds": 86400,
        "retentionEndsAt": "2026-09-27T12:04:00Z",
    }
    value.update(updates)
    return encoded(value)


class FakeTransport:
    def __init__(self, results=(429, 429, 200, 200)):
        self.results = iter(results)
        self.calls = []

    def request(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result


def run(results=(429, 429, 200, 200)):
    plan = plan_bytes()
    transport = FakeTransport(results)
    return observer.observe(plan, review(plan), transport, now=NOW), transport


@pytest.mark.parametrize("value", [True, 1.0])
@pytest.mark.parametrize("document", ["plan", "review"])
def test_schema_versions_require_exact_integers_before_transport(document, value):
    plan = plan_bytes()
    declaration = review(plan)
    if document == "plan":
        changed = json.loads(plan)
        changed["schemaVersion"] = value
        plan = encoded(changed)
        declaration = review(plan)
    else:
        changed = json.loads(declaration)
        changed["schemaVersion"] = value
        declaration = encoded(changed)
    transport = FakeTransport()

    with pytest.raises(observer.ObserverError, match="schema-version"):
        observer.observe(plan, declaration, transport, now=NOW)

    assert transport.calls == []


def test_boolean_future_skew_is_rejected_before_transport():
    plan = json.loads(plan_bytes())
    plan["policy"]["maxFutureSkewSeconds"] = False
    raw = encoded(plan)
    transport = FakeTransport()

    with pytest.raises(observer.ObserverError, match="policy-drift"):
        observer.observe(raw, review(raw), transport, now=NOW)

    assert transport.calls == []


def test_list_review_decision_is_rejected_before_transport():
    plan = plan_bytes()
    transport = FakeTransport()

    with pytest.raises(observer.ObserverError, match="second-review-invalid"):
        observer.observe(plan, review(plan, decision=["approved"]), transport, now=NOW)

    assert transport.calls == []


def test_exact_tuple_uses_four_fixed_one_shot_gets_and_safe_evidence():
    result, transport = run()
    assert result["outcome"] == "success"
    assert [route["status"] for route in result["routes"]] == [429, 429, 200, 200]
    assert transport.calls == [
        {
            "method": "GET",
            "url": f"https://staging.token.place{path}",
            "timeout": 5,
            "follow_redirects": False,
        }
        for path in ("/", "/api/v1/meta", "/livez", "/healthz")
    ]
    assert result["quotaDrillEvidence"] is False
    assert result["originAttributed"] is False
    assert result["cleanupState"] == "cleanup-pending"
    assert result["cleanupRequired"]["observerPerformedCleanup"] is False


@pytest.mark.parametrize("statuses", [(200,), (429, 200), (429, 429, 429), (429, 429, 200, 429)])
def test_every_unexpected_status_stops_without_fabricating_unattempted_statuses(statuses):
    result, transport = run(statuses)
    assert result["outcome"] == "failed"
    assert len(transport.calls) == len(statuses)
    assert [route["observed"] for route in result["routes"]] == [
        index < len(statuses) for index in range(4)
    ]
    assert all(route["status"] is None for route in result["routes"][len(statuses) :])


@pytest.mark.parametrize("status", [300, 301, 302, 307, 308, 399])
def test_redirects_are_rejected_and_not_followed(status):
    result, transport = run((status,))
    assert result["reason"] == "redirect-rejected"
    assert len(transport.calls) == 1
    assert transport.calls[0]["follow_redirects"] is False


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("private"), ConnectionError("private"), OSError("private"), KeyboardInterrupt()],
)
def test_timeout_dns_tls_transport_and_interruption_are_redacted_and_not_retried(failure):
    result, transport = run((failure,))
    assert result["outcome"] == "failed"
    assert result["reason"] == "observation-interrupted"
    assert len(transport.calls) == 1
    assert "private" not in json.dumps(result)


def test_ordinary_transport_exception_is_redacted_and_not_retried():
    result, transport = run((RuntimeError("sensitive transport detail"),))

    assert result["outcome"] == "failed"
    assert result["reason"] == "observation-interrupted"
    assert result["cleanupState"] == "cleanup-pending"
    assert len(transport.calls) == 1
    assert "sensitive transport detail" not in json.dumps(result)


@pytest.mark.parametrize("status", [None, True, "429", 99, 600])
def test_malformed_transport_result_fails_closed(status):
    result, _ = run((status,))
    assert result["outcome"] == "failed"
    assert result["routes"][0]["status"] is None


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
        ("target", "healthControlPaths", ["/livez"]),
        ("target", "followRedirects", True),
        ("authorization", "lifecycle", "quota-exhaustion"),
    ],
)
def test_plan_target_and_lifecycle_drift_fail_before_transport(section, field, replacement):
    plan = json.loads(plan_bytes())
    plan[section][field] = replacement
    transport = FakeTransport()
    raw = encoded(plan)
    with pytest.raises(observer.ObserverError):
        observer.observe(raw, review(raw), transport, now=NOW)
    assert transport.calls == []


@pytest.mark.parametrize(
    "updates",
    [
        {"lifecycle": "quota-exhaustion"},
        {"decision": "rejected"},
        {"reviewer": "independent reviewer"},
        {"declaredAt": "2026-09-26T12:06:00Z"},
        {"declaredAt": "2026-09-25T12:04:00Z"},
        {"planSha256": "sha256:" + "0" * 64},
        {"ruleIdentitySha256": "sha256:" + "0" * 64},
        {"retentionSeconds": 2},
        {"retentionEndsAt": "2026-09-27T12:03:59Z"},
    ],
)
def test_second_review_must_be_current_distinct_and_bound(updates):
    plan = plan_bytes()
    transport = FakeTransport()
    if updates == {"decision": "rejected"}:
        result = observer.observe(plan, review(plan, **updates), transport, now=NOW)
        assert result["reason"] == "review-rejected"
    else:
        with pytest.raises(observer.ObserverError):
            observer.observe(plan, review(plan, **updates), transport, now=NOW)
    assert transport.calls == []


def test_duplicate_unknown_and_privacy_fields_are_rejected():
    plan = plan_bytes()
    good = json.loads(review(plan))
    for bad in (
        review(plan)[:-1] + b',"reviewer":"duplicate"}',
        encoded(good | {"unknown": 1}),
        encoded(good | {"responseBody": "secret"}),
    ):
        with pytest.raises(observer.ObserverError):
            observer.validate_inputs(plan, bad, now=NOW)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 26, 11, 59, tzinfo=timezone.utc),
        datetime(2026, 9, 26, 12, 20, tzinfo=timezone.utc),
    ],
)
def test_future_or_expired_plan_fails_closed_without_transport(now):
    plan = plan_bytes()
    transport = FakeTransport()
    if now < NOW:
        with pytest.raises(observer.ObserverError):
            observer.observe(plan, review(plan), transport, now=now)
    else:
        result = observer.observe(plan, review(plan), transport, now=now)
        assert result["reason"] == "authorization-expired"
        assert result["cleanupState"] == "cleanup-pending"
    assert transport.calls == []


def test_abandonment_is_never_started_failed_and_cleanup_pending():
    plan = plan_bytes()
    result = observer.abandon(plan, review(plan), now=NOW)
    assert result["outcome"] == "failed"
    assert result["reason"] == "abandoned"
    assert all(
        route == {"path": path, "observed": False, "status": None}
        for route, path in zip(result["routes"], ("/", "/api/v1/meta", "/livez", "/healthz"))
    )
    assert result["cleanupRequired"]["required"] is True


def test_expired_abandonment_still_emits_overdue_cleanup_signal():
    plan = plan_bytes()
    result = observer.abandon(
        plan, review(plan), now=datetime(2026, 9, 26, 12, 20, tzinfo=timezone.utc)
    )
    assert result["reason"] == "abandoned"
    assert result["cleanupRequired"]["deadlineMissed"] is True
    assert result["cleanupRequired"]["escalationRequired"] is True


def test_rejected_review_abandonment_emits_cleanup_without_transport():
    plan = plan_bytes()
    result = observer.abandon(plan, review(plan, decision="rejected"), now=NOW)
    assert result["outcome"] == "failed"
    assert result["reason"] == "abandoned"
    assert result["cleanupState"] == "cleanup-pending"
    assert all(route["observed"] is False for route in result["routes"])


def test_reviewer_names_cannot_use_outer_whitespace_to_evade_identity_check():
    plan = plan_bytes()
    with pytest.raises(observer.ObserverError, match="named-value-invalid"):
        observer.validate_inputs(plan, review(plan, reviewer="second reviewer "), now=NOW)


@pytest.mark.parametrize("field", ["approvedTimeoutSeconds", "approvedRetentionSeconds"])
@pytest.mark.parametrize("value", [None, True, "5", 0])
def test_approved_policy_bounds_require_positive_integers(field, value):
    plan = json.loads(plan_bytes())
    plan["policy"][field] = value
    raw = encoded(plan)
    with pytest.raises(observer.ObserverError, match="policy-drift"):
        observer.validate_inputs(raw, review(raw), now=NOW)


def test_observation_digest_binds_the_complete_initial_record():
    result, _ = run()
    claimed = result.pop("observationSha256")
    assert claimed == digest(encoded(result))
    result["outcome"] = "failed"
    assert claimed != digest(encoded(result))


def test_privacy_walk_is_iterative_for_deep_decoded_values():
    value = {}
    for _ in range(2000):
        value = {"safe": value}
    observer._privacy(value)


def test_rechecks_authorization_between_requests_and_uses_completion_time(monkeypatch):
    plan = plan_bytes()
    instants = iter(
        [
            NOW,
            NOW,
            datetime(2026, 9, 26, 12, 10, tzinfo=timezone.utc),
            datetime(2026, 9, 26, 12, 21, tzinfo=timezone.utc),
            datetime(2026, 9, 26, 12, 21, tzinfo=timezone.utc),
        ]
    )
    monkeypatch.setattr(observer, "_observation_time", lambda unused: next(instants))
    result = observer.observe(plan, review(plan), FakeTransport(), now=None)
    assert result["reason"] == "authorization-expired"
    assert result["routes"][2]["observed"] is False
    assert result["cleanupRequired"]["deadlineMissed"] is True


def test_cli_help_exposes_standalone_lifecycle_options():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/tokenplace_static_429_observer.py"), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "--lifecycle" in completed.stdout
    assert "authorized-static-emulation" in completed.stdout
    assert "--acknowledge-cleanup" in completed.stdout
    assert "--abandon" in completed.stdout


@pytest.mark.parametrize("lifecycle", [None, "quota-exhaustion"])
def test_cli_requires_exact_lifecycle_before_observation(tmp_path, monkeypatch, lifecycle):
    plan = plan_bytes()
    plan_path = tmp_path / "plan.json"
    review_path = tmp_path / "review.json"
    plan_path.write_bytes(plan)
    review_path.write_bytes(review(plan))
    called = False

    def unexpected_observe(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal called
        called = True
        raise AssertionError("observation must not start")

    monkeypatch.setattr(observer, "observe", unexpected_observe)
    arguments = [
        "--plan",
        str(plan_path),
        "--review",
        str(review_path),
        "--output",
        "-",
        "--acknowledge-cleanup",
    ]
    if lifecycle is not None:
        arguments.extend(("--lifecycle", lifecycle))

    with pytest.raises(SystemExit, match="2"):
        observer.main(arguments)
    assert called is False


def test_cli_observes_with_explicit_lifecycle(tmp_path, monkeypatch):
    plan = plan_bytes()
    plan_path = tmp_path / "plan.json"
    review_path = tmp_path / "review.json"
    plan_path.write_bytes(plan)
    review_path.write_bytes(review(plan))
    monkeypatch.setattr(observer, "observe", lambda *args, **kwargs: {"outcome": "success"})
    written = {}
    monkeypatch.setattr(observer, "_write_record", lambda path, record: written.update(record))

    status = observer.main(
        [
            "--plan",
            str(plan_path),
            "--review",
            str(review_path),
            "--output",
            "-",
            "--lifecycle",
            "authorized-static-emulation",
            "--acknowledge-cleanup",
        ]
    )

    assert status == 0
    assert written == {"outcome": "success"}


def test_cli_abandon_writes_evidence_without_network(tmp_path):
    plan = plan_bytes()
    plan_path = tmp_path / "plan.json"
    review_path = tmp_path / "review.json"
    output_path = tmp_path / "evidence.json"
    plan_path.write_bytes(plan)
    review_path.write_bytes(review(plan))
    status = observer.main(
        [
            "--plan",
            str(plan_path),
            "--review",
            str(review_path),
            "--output",
            str(output_path),
            "--lifecycle",
            "authorized-static-emulation",
            "--acknowledge-cleanup",
            "--abandon",
        ]
    )
    # The fixture authorization is stale against the real CLI clock and must be
    # rejected even in abandonment mode.
    assert status == 2
    assert not output_path.exists()


def cleanup(result, **updates):  # noqa: ANN003
    proof = b"privacy-safe independent absence proof"
    value = {
        "schemaVersion": 1,
        "reviewer": "cleanup reviewer",
        "decision": "absent",
        "declaredAt": "2026-09-26T12:06:00Z",
        "ruleIdentitySha256": digest(IDENTITY),
        "cleanupProofSha256": digest(proof),
    }
    value.update(updates)
    return observer.attest_cleanup(result, encoded(value), proof, now=NOW + timedelta(minutes=2))


def test_identity_bound_cleanup_closes_obligation_without_rewriting_failed_outcome():
    failed, _ = run((500,))
    closed = cleanup(failed)
    assert failed["cleanupState"] == "cleanup-pending"
    assert closed["cleanupState"] == "cleanup-proven"
    assert closed["outcome"] == "failed"
    assert closed["routes"] == failed["routes"]
    assert closed["cleanupAttestation"]["authenticated"] is False
    assert closed["cleanupAttestation"]["independentlyProven"] is False
    assert closed["cleanupAttestation"]["cleanupAttestationSha256"].startswith("sha256:")


@pytest.mark.parametrize(
    "updates",
    [
        {"reviewer": "second reviewer"},
        {"decision": "present"},
        {"declaredAt": "2026-09-26T12:20:00Z"},
        {"declaredAt": "2026-09-26T11:00:00Z"},
        {"ruleIdentitySha256": "sha256:" + "0" * 64},
        {"cleanupProofSha256": "sha256:" + "0" * 64},
    ],
)
def test_cleanup_proof_must_be_fresh_independent_and_identity_bound(updates):
    result, _ = run()
    with pytest.raises(observer.ObserverError):
        cleanup(result, **updates)


@pytest.mark.parametrize("reviewer", ["independent reviewer", "staging edge owner"])
def test_cleanup_reviewer_is_independent_of_rule_review_and_removal_owner(reviewer):
    result, _ = run()
    with pytest.raises(observer.ObserverError, match="cleanup-review-not-independent"):
        cleanup(result, reviewer=reviewer)


@pytest.mark.parametrize("field", ["outcome", "reason", "observedAt", "planSha256"])
def test_cleanup_rejects_tampered_observation_evidence(field):
    result, _ = run()
    result[field] = "tampered"
    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


def test_cleanup_rejects_malformed_nested_record_even_with_recomputed_digest():
    result, _ = run()
    result["routes"][0]["status"] = "429"
    unsigned = dict(result)
    unsigned.pop("observationSha256")
    result["observationSha256"] = digest(encoded(unsigned))
    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


@pytest.mark.parametrize("value", [True, 1.0])
def test_cleanup_rejects_non_integer_record_schema_version(value):
    result, _ = run()
    result["schemaVersion"] = value
    unsigned = dict(result)
    unsigned.pop("observationSha256")
    result["observationSha256"] = digest(encoded(unsigned))

    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


def test_cleanup_rejects_list_outcome_as_observer_error():
    result, _ = run()
    result["outcome"] = ["success"]
    unsigned = dict(result)
    unsigned.pop("observationSha256")
    result["observationSha256"] = digest(encoded(unsigned))

    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


@pytest.mark.parametrize("value", [False, 1.0])
def test_cleanup_attestation_schema_version_requires_exact_integer(value):
    result, _ = run()

    with pytest.raises(observer.ObserverError, match="cleanup-attestation-invalid"):
        cleanup(result, schemaVersion=value)


def test_cleanup_rejects_inconsistent_success_even_with_recomputed_digest():
    result, _ = run()
    result["routes"][0]["status"] = 200
    unsigned = dict(result)
    unsigned.pop("observationSha256")
    result["observationSha256"] = digest(encoded(unsigned))

    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


def test_cleanup_rejects_failed_record_using_success_reason():
    result, _ = run((500,))
    result["reason"] = "exact-status-tuple"
    unsigned = dict(result)
    unsigned.pop("observationSha256")
    result["observationSha256"] = digest(encoded(unsigned))

    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


def test_second_review_artifacts_are_bound_alongside_retention():
    plan = plan_bytes()
    declaration = review(plan)
    result = observer.observe(plan, declaration, FakeTransport(), now=NOW)
    assert result["evidencePolicy"]["secondReviewDeclaredAt"] == "2026-09-26T12:04:00Z"
    assert result["evidencePolicy"]["secondReviewSha256"] == digest(declaration)
    assert result["secondReviewerDeclaration"]["sha256"] == digest(declaration)


@pytest.mark.parametrize(
    "field",
    sorted(observer.POLICY_FIELDS - {"maxFutureSkewSeconds"}),
)
@pytest.mark.parametrize("value", [None, True, "5", 0])
def test_every_caller_policy_bound_requires_a_positive_integer(field, value):
    plan = json.loads(plan_bytes())
    plan["policy"][field] = value
    raw = encoded(plan)
    with pytest.raises(observer.ObserverError):
        observer.validate_inputs(raw, review(raw), now=NOW)


def test_authorization_reviewer_scope_and_review_window_are_bound():
    for field, value in (
        ("approvedReviewer", "different reviewer"),
        ("approvedScopeSha256", "sha256:" + "0" * 64),
        ("reviewStartsAt", "2026-09-26T12:05:00Z"),
    ):
        plan = json.loads(plan_bytes())
        plan["authorization"][field] = value
        raw = encoded(plan)
        with pytest.raises(observer.ObserverError):
            observer.observe(raw, review(raw), FakeTransport(), now=NOW)


@pytest.mark.parametrize(
    ("method", "url", "follow_redirects"),
    [
        ("POST", "https://staging.token.place/", False),
        ("GET", "http://staging.token.place/", False),
        ("GET", "https://staging.token.place/other", False),
        ("GET", "https://staging.token.place/@evil", False),
        ("GET", "https://staging.token.place/", True),
    ],
)
def test_urllib_transport_direct_use_rejects_noncanonical_requests(method, url, follow_redirects):
    transport = observer.UrllibTransport()
    with pytest.raises(observer.ObserverError, match="transport-contract"):
        transport.request(method=method, url=url, timeout=1, follow_redirects=follow_redirects)


def test_urllib_transport_redacts_underlying_failures_without_retry():
    class FailingOpener:
        def __init__(self):
            self.calls = 0

        def open(self, request, timeout):  # noqa: ANN001, ANN201, ARG002
            self.calls += 1
            raise urllib.error.URLError("private host detail")

    transport = observer.UrllibTransport()
    transport._opener = FailingOpener()
    with pytest.raises(observer.ObserverError, match="^transport-failure$") as caught:
        transport.request(
            method="GET",
            url="https://staging.token.place/",
            timeout=1,
            follow_redirects=False,
        )
    assert "private" not in str(caught.value)
    assert transport._opener.calls == 1


def test_missed_deadline_signal_names_escalation_without_performing_cleanup():
    plan = json.loads(plan_bytes())
    plan["authorization"]["removalDeadline"] = "2026-09-26T12:05:00Z"
    # Validation prevents starting at the deadline; the local signal still handles a run
    # whose request completes after its preflight validation.
    validated, second = observer.validate_inputs(plan_bytes(), review(plan_bytes()), now=NOW)
    signal = observer._signal(validated, NOW)  # noqa: SLF001 - focused contract test
    assert signal["deadlineMissed"] is False
    signal = observer._signal(validated, datetime(2026, 9, 26, 12, 21, tzinfo=timezone.utc))
    assert signal["escalationRequired"] is True
    assert signal["escalation"] == "staging incident channel"
    assert signal["observerPerformedCleanup"] is False


def test_module_has_no_mutation_or_quota_runner_surface_and_planner_is_unchanged():
    source = (ROOT / "scripts/tokenplace_static_429_observer.py").read_text()
    lowered = source.lower()
    for forbidden in (
        "cloudflare",
        "kubernetes",
        "servicemonitor",
        "deployment",
        "registry",
        "subprocess",
    ):
        assert forbidden not in lowered
    assert "tokenplace_incident_drill" not in source
    assert (
        "tokenplace_static_429_observer"
        not in (ROOT / "scripts/tokenplace_incident_drill.py").read_text()
    )
    assert (
        hashlib.sha256((ROOT / "scripts/tokenplace_static_429_plan.py").read_bytes()).hexdigest()
        == "3c3ee3a00387d6bb11dfb3d5605e3635c41ca7534208a1689991bee7f79522bb"
    )


def test_redirect_handler_and_urllib_response_contract(monkeypatch):
    assert observer.RejectRedirects().redirect_request(None, None, None, None, None, None) is None

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return None

    class Opener:
        def open(self, request, timeout):  # noqa: ANN001, ANN201, ARG002
            return Response()

    transport = observer.UrllibTransport()
    transport._opener = Opener()
    assert (
        transport.request(
            method="GET",
            url="https://staging.token.place/healthz",
            timeout=1,
            follow_redirects=False,
        )
        == 200
    )

    error = urllib.error.HTTPError("safe", 429, "expected", {}, None)
    monkeypatch.setattr(
        transport._opener, "open", lambda *args, **kwargs: (_ for _ in ()).throw(error)
    )
    assert (
        transport.request(
            method="GET",
            url="https://staging.token.place/",
            timeout=1,
            follow_redirects=False,
        )
        == 429
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"[]", "schema-mismatch"),
        (b'"unterminated', "malformed-input"),
    ],
)
def test_json_loader_fails_closed_for_non_object_or_malformed_input(raw, reason):
    with pytest.raises(observer.ObserverError, match=reason):
        observer._load(raw)


@pytest.mark.parametrize(
    "value",
    ["not-a-time", "2026-09-26T12:05:00+00:00", "2026-09-26T12:05:00.1Z"],
)
def test_timestamp_parser_requires_canonical_utc_seconds(value):
    with pytest.raises(observer.ObserverError, match="timestamp-invalid"):
        observer._time(value)


def test_timestamp_parser_sanitizes_invalid_calendar_values_ending_in_z():
    with pytest.raises(observer.ObserverError, match="^timestamp-invalid$"):
        observer._time("2026-02-30T12:05:00Z")


def test_clock_requires_utc_without_fractional_seconds():
    for value in (
        NOW.replace(tzinfo=None),
        NOW.replace(microsecond=1),
    ):
        with pytest.raises(observer.ObserverError, match="clock-invalid"):
            observer._observation_time(value)


@pytest.mark.parametrize(
    ("section", "field", "value", "reason"),
    [
        (None, "planType", "different", "plan-kind"),
        ("target", "authority", "different.example", "target-drift"),
        (None, "expectedStatuses", {}, "status-contract-drift"),
        ("reviewerDeclaration", "decision", "rejected", "rule-review-invalid"),
        ("reviewerDeclaration", "authenticated", True, "declaration-overclaim"),
        (None, "inputSha256", "bad", "digest-invalid"),
        (
            "authorization",
            "approvedRuleIdentitySha256",
            "sha256:" + "0" * 64,
            "rule-identity-mismatch",
        ),
        ("authorization", "approvedReviewer", "different", "rule-reviewer-mismatch"),
    ],
)
def test_preflight_reports_specific_contract_drift(section, field, value, reason):
    plan = json.loads(plan_bytes())
    (plan if section is None else plan[section])[field] = value
    raw = encoded(plan)
    with pytest.raises(observer.ObserverError, match=reason):
        observer.validate_inputs(raw, review(raw), now=NOW)


@pytest.mark.parametrize(
    ("mutate", "now", "reason"),
    [
        (
            lambda plan: plan["authorization"].__setitem__(
                "reviewStartsAt", "2026-09-26T12:46:00Z"
            ),
            NOW,
            "authorization-window-invalid",
        ),
        (
            lambda plan: plan["authorization"].__setitem__("expiresAt", "2026-09-26T14:00:00Z"),
            NOW,
            "authorization-window-invalid",
        ),
        (
            lambda plan: None,
            datetime(2026, 9, 26, 11, 54, tzinfo=timezone.utc),
            "plan-evidence-future",
        ),
        (lambda plan: None, datetime(2026, 9, 26, 12, 20, tzinfo=timezone.utc), "plan-expired"),
        (
            lambda plan: plan["authorization"].__setitem__(
                "removalDeadline", "2026-09-26T12:04:00Z"
            ),
            NOW,
            "plan-expired",
        ),
    ],
)
def test_direct_validation_rejects_invalid_authorization_before_transport(mutate, now, reason):
    plan = json.loads(plan_bytes())
    mutate(plan)
    raw = encoded(plan)
    transport = FakeTransport()

    with pytest.raises(observer.ObserverError, match=f"^{reason}$"):
        observer.validate_inputs(raw, review(raw), now=now)

    assert transport.calls == []


def test_cleanup_rejects_wrong_route_count_and_invalid_names():
    result, _ = run()
    for mutate in (
        lambda record: record["routes"].pop(),
        lambda record: record.__setitem__("ruleScopeReviewer", " bad"),
    ):
        changed = json.loads(json.dumps(result))
        mutate(changed)
        changed["observationSha256"] = digest(
            encoded({key: value for key, value in changed.items() if key != "observationSha256"})
        )
        with pytest.raises(
            observer.ObserverError, match="observation-record-invalid|named-value-invalid"
        ):
            cleanup(changed)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: (
            record["evidencePolicy"].__setitem__("secondReviewSha256", "invalid"),
            record["secondReviewerDeclaration"].__setitem__("sha256", "invalid"),
        ),
        lambda record: record["cleanupRequired"].__setitem__("required", False),
    ],
)
def test_cleanup_rejects_malformed_digests_and_signals_with_recomputed_hash(mutate):
    result, _ = run()
    mutate(result)
    result["observationSha256"] = digest(
        encoded({key: value for key, value in result.items() if key != "observationSha256"})
    )

    with pytest.raises(observer.ObserverError, match="^observation-record-invalid$"):
        cleanup(result)


def test_cleanup_rejects_structurally_valid_tampering_without_a_matching_hash():
    result, _ = run()
    result["reviewedConfigurationSha256"] = "sha256:" + "0" * 64

    with pytest.raises(observer.ObserverError, match="^observation-record-invalid$"):
        cleanup(result)


def test_completion_after_deadline_converts_success_to_failure(monkeypatch):
    instants = iter([NOW] * 5 + [datetime(2026, 9, 26, 12, 21, tzinfo=timezone.utc)])
    monkeypatch.setattr(observer, "_observation_time", lambda unused: next(instants))
    plan = plan_bytes()
    result = observer.observe(plan, review(plan), FakeTransport(), now=None)
    assert result["outcome"] == "failed"
    assert result["reason"] == "authorization-expired"


def test_cleanup_rejects_invalid_record_policy_even_with_valid_digest():
    result, _ = run()
    result["evidencePolicy"]["freshnessSeconds"] = 0
    result["observationSha256"] = digest(
        encoded({key: value for key, value in result.items() if key != "observationSha256"})
    )
    with pytest.raises(observer.ObserverError, match="observation-record-invalid"):
        cleanup(result)


def test_record_writer_is_atomic_and_refuses_overwrite(tmp_path):
    path = tmp_path / "record.json"
    observer._write_record(str(path), {"outcome": "failed"})
    assert json.loads(path.read_text()) == {"outcome": "failed"}
    with pytest.raises(FileExistsError):
        observer._write_record(str(path), {"outcome": "success"})
    assert not list(tmp_path.glob("*.tmp.*"))


def test_record_writer_tolerates_a_temporary_file_removed_during_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "record.json"

    def remove_temporary_then_fail(temporary, destination):  # noqa: ANN001, ARG001
        Path(temporary).unlink()
        raise OSError("simulated link failure")

    monkeypatch.setattr(observer.os, "link", remove_temporary_then_fail)
    with pytest.raises(OSError, match="simulated link failure"):
        observer._write_record(str(path), {"outcome": "failed"})
    assert not path.exists()


def test_cli_returns_failed_outcome_status_and_redacts_errors(tmp_path, capsys, monkeypatch):
    plan = plan_bytes()
    plan_path = tmp_path / "plan.json"
    review_path = tmp_path / "review.json"
    plan_path.write_bytes(plan)
    review_path.write_bytes(review(plan))
    monkeypatch.setattr(observer, "abandon", lambda *args, **kwargs: {"outcome": "failed"})
    assert (
        observer.main(
            [
                "--plan",
                str(plan_path),
                "--review",
                str(review_path),
                "--output",
                "-",
                "--lifecycle",
                "authorized-static-emulation",
                "--acknowledge-cleanup",
                "--abandon",
            ]
        )
        == 1
    )
    monkeypatch.setattr(
        observer, "abandon", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("secret"))
    )
    assert (
        observer.main(
            [
                "--plan",
                str(plan_path),
                "--review",
                str(review_path),
                "--output",
                "-",
                "--lifecycle",
                "authorized-static-emulation",
                "--acknowledge-cleanup",
                "--abandon",
            ]
        )
        == 2
    )
    assert "secret" not in capsys.readouterr().err
