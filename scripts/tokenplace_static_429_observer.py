#!/usr/bin/env python3
"""Bounded observer for an approved, pre-existing static-429 staging rule.

The observer can only issue four fixed GET requests.  It deliberately has no rule
management or cleanup capability; attestations accepted here are declarations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from tokenplace_static_429_plan import (  # type: ignore[import-not-found]
    AUTHORITY,
    HEALTH_ROUTES,
    LIFECYCLE,
    ROUTES,
)

SCHEMA_VERSION = 1
EXPECTED = {"/": 429, "/api/v1/meta": 429, "/livez": 200, "/healthz": 200}
SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
PLAN_FIELDS = {
    "schemaVersion",
    "planType",
    "executable",
    "networkCapable",
    "mutationCapable",
    "quotaDrillEvidence",
    "inputSha256",
    "ruleIdentitySha256",
    "reviewedConfigurationSha256",
    "target",
    "expectedStatuses",
    "authorization",
    "reviewerDeclaration",
    "policy",
}
TARGET_FIELDS = {
    "scheme",
    "authority",
    "method",
    "emulationPaths",
    "healthControlPaths",
    "followRedirects",
}
AUTH_FIELDS = {
    "lifecycle",
    "authorizedAt",
    "expiresAt",
    "rehearsalStartsAt",
    "rehearsalEndsAt",
    "reviewStartsAt",
    "reviewEndsAt",
    "removalDeadline",
    "removalOwner",
    "handoff",
    "escalation",
    "approvedRuleIdentitySha256",
    "approvedReviewer",
    "approvedScopeSha256",
}
DECLARATION_FIELDS = {
    "reviewer",
    "decision",
    "declaredAt",
    "authenticated",
    "independentlyProven",
}
POLICY_FIELDS = {
    "approvedAuthorizationLifetimeSeconds",
    "approvedEvidenceAgeSeconds",
    "approvedRetentionSeconds",
    "approvedTimeoutSeconds",
    "maxEvidenceAgeSeconds",
    "maxFutureSkewSeconds",
    "maxRehearsalWindowSeconds",
    "maxReviewWindowSeconds",
    "timeoutSeconds",
    "retentionSeconds",
}
REVIEW_FIELDS = {
    "schemaVersion",
    "lifecycle",
    "reviewer",
    "decision",
    "declaredAt",
    "planSha256",
    "ruleIdentitySha256",
    "retentionSeconds",
    "retentionEndsAt",
}
CLEANUP_FIELDS = {
    "schemaVersion",
    "reviewer",
    "decision",
    "declaredAt",
    "ruleIdentitySha256",
    "cleanupProofSha256",
}
RECORD_FIELDS = {
    "schemaVersion",
    "evidenceType",
    "lifecycle",
    "observedAt",
    "outcome",
    "reason",
    "cleanupState",
    "quotaDrillEvidence",
    "originAttributed",
    "planSha256",
    "reviewedConfigurationSha256",
    "secondReviewerDeclaration",
    "evidencePolicy",
    "ruleScopeReviewer",
    "routes",
    "cleanupRequired",
    "cleanupAttestation",
    "observationSha256",
}
PROHIBITED_KEYS = {
    "token",
    "tokens",
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "body",
    "responsebody",
    "callerid",
    "requestid",
    "rawrule",
    "ruleexpression",
    "query",
    "privateurl",
    "headers",
    "requestheaders",
    "responseheaders",
    "prompt",
    "prompts",
    "response",
    "responses",
    "ciphertext",
    "error",
    "errors",
    "authorizationheader",
}


class ObserverError(ValueError):
    """An observer input fails closed without reflecting private input."""


class Transport(Protocol):
    def request(self, *, method: str, url: str, timeout: float, follow_redirects: bool) -> int:
        """Return an integer status without returning headers or a body."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent urllib from converting a single observation into another request."""

    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url
    ):  # noqa: ANN001, ANN201, ARG002
        return None


class UrllibTransport:
    """Minimal concrete transport; it exposes no response content to the observer."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(RejectRedirects)

    def request(self, *, method: str, url: str, timeout: float, follow_redirects: bool) -> int:
        allowed_urls = {f"https://{AUTHORITY}{path}" for path in ROUTES}
        if (
            method != "GET"
            or follow_redirects
            or url not in allowed_urls
            or type(timeout) not in (int, float)
            or timeout <= 0
        ):
            raise ObserverError("transport-contract")
        request = urllib.request.Request(url, method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            # HTTPError is urllib's representation for both the expected 429 and
            # rejected redirects.  Only the integer status crosses this boundary.
            exc.close()
            return exc.code
        except OSError as exc:
            raise ObserverError("transport-failure") from exc


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _scope_digest(target: dict[str, Any]) -> str:
    return _digest(_canonical({field: target[field] for field in TARGET_FIELDS}))


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ObserverError("duplicate-field")
        value[key] = child
    return value


def _load(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except ObserverError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ObserverError("malformed-input") from exc
    if not isinstance(value, dict):
        raise ObserverError("schema-mismatch")
    _privacy(value)
    return value


def _privacy(value: Any) -> None:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if re.sub(r"[^a-z]", "", key.lower()) in PROHIBITED_KEYS:
                    raise ObserverError("privacy-field")
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def _exact(value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ObserverError("schema-mismatch")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ObserverError("timestamp-invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ObserverError("timestamp-invalid") from exc
    if (
        parsed.tzinfo != timezone.utc
        or parsed.microsecond
        or value != parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    ):
        raise ObserverError("timestamp-invalid")
    return parsed


def _now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    if current.tzinfo != timezone.utc or current.microsecond:
        raise ObserverError("clock-invalid")
    return current


def _safe_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", value)
    ):
        raise ObserverError("named-value-invalid")
    return value


def validate_inputs(
    plan_raw: bytes,
    review_raw: bytes,
    *,
    now: datetime | None = None,
    allow_expired: bool = False,
    allow_rejected: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate an immutable planner output and the required second declaration."""
    plan = _exact(_load(plan_raw), PLAN_FIELDS)
    review = _exact(_load(review_raw), REVIEW_FIELDS)
    current = _now(now)
    if plan["schemaVersion"] != 1 or review["schemaVersion"] != SCHEMA_VERSION:
        raise ObserverError("schema-version")
    if (
        plan["planType"],
        plan["executable"],
        plan["networkCapable"],
        plan["mutationCapable"],
        plan["quotaDrillEvidence"],
    ) != ("offline-static-429-boundary-emulation", False, False, False, False):
        raise ObserverError("plan-kind")
    target = _exact(plan["target"], TARGET_FIELDS)
    if target != {
        "scheme": "https",
        "authority": AUTHORITY,
        "method": "GET",
        "emulationPaths": ["/", "/api/v1/meta"],
        "healthControlPaths": list(HEALTH_ROUTES),
        "followRedirects": False,
    }:
        raise ObserverError("target-drift")
    if plan["expectedStatuses"] != EXPECTED:
        raise ObserverError("status-contract-drift")
    authorization = _exact(plan["authorization"], AUTH_FIELDS)
    declaration = _exact(plan["reviewerDeclaration"], DECLARATION_FIELDS)
    policy = _exact(plan["policy"], POLICY_FIELDS)
    if authorization.get("lifecycle") != LIFECYCLE:
        raise ObserverError("lifecycle-invalid")
    if not isinstance(declaration, dict) or declaration.get("decision") != "approved":
        raise ObserverError("rule-review-invalid")
    if (
        declaration.get("authenticated") is not False
        or declaration.get("independentlyProven") is not False
    ):
        raise ObserverError("declaration-overclaim")
    for digest in (
        plan["inputSha256"],
        plan["ruleIdentitySha256"],
        plan["reviewedConfigurationSha256"],
    ):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ObserverError("digest-invalid")
    rule_reviewer = _safe_name(declaration.get("reviewer"))
    for field in ("removalOwner", "handoff", "escalation"):
        _safe_name(authorization.get(field))
    if authorization.get("approvedRuleIdentitySha256") != plan["ruleIdentitySha256"]:
        raise ObserverError("rule-identity-mismatch")
    if authorization.get("approvedReviewer") != rule_reviewer:
        raise ObserverError("rule-reviewer-mismatch")
    if authorization.get("approvedScopeSha256") != _scope_digest(target):
        raise ObserverError("scope-mismatch")
    if type(policy.get("timeoutSeconds")) is not int or policy["timeoutSeconds"] < 1:
        raise ObserverError("timeout-invalid")
    if type(policy.get("retentionSeconds")) is not int or policy["retentionSeconds"] < 1:
        raise ObserverError("retention-invalid")
    for field in POLICY_FIELDS - {"maxFutureSkewSeconds", "timeoutSeconds", "retentionSeconds"}:
        if type(policy.get(field)) is not int or policy[field] < 1:
            raise ObserverError("policy-drift")
    if (
        policy["maxFutureSkewSeconds"] != 0
        or policy["maxEvidenceAgeSeconds"] > policy["approvedEvidenceAgeSeconds"]
        or policy["timeoutSeconds"] > policy["approvedTimeoutSeconds"]
        or policy["retentionSeconds"] > policy["approvedRetentionSeconds"]
        or policy["maxRehearsalWindowSeconds"] > policy["approvedAuthorizationLifetimeSeconds"]
        or policy["maxReviewWindowSeconds"] > policy["approvedAuthorizationLifetimeSeconds"]
    ):
        raise ObserverError("policy-drift")
    authorized = _time(authorization["authorizedAt"])
    rule_declared = _time(declaration["declaredAt"])
    rehearsal_starts = _time(authorization["rehearsalStartsAt"])
    rehearsal_ends = _time(authorization["rehearsalEndsAt"])
    expires = _time(authorization["expiresAt"])
    removal_deadline = _time(authorization["removalDeadline"])
    review_starts = _time(authorization["reviewStartsAt"])
    review_ends = _time(authorization["reviewEndsAt"])
    if not (
        authorized <= rehearsal_starts < rehearsal_ends <= expires
        and rehearsal_starts <= review_starts < review_ends <= expires
        and rehearsal_starts <= removal_deadline <= rehearsal_ends
    ):
        raise ObserverError("authorization-window-invalid")
    if (
        (expires - authorized).total_seconds() > policy["approvedAuthorizationLifetimeSeconds"]
        or (rehearsal_ends - rehearsal_starts).total_seconds() > policy["maxRehearsalWindowSeconds"]
        or (review_ends - review_starts).total_seconds() > policy["maxReviewWindowSeconds"]
        or policy["timeoutSeconds"] > (rehearsal_ends - rehearsal_starts).total_seconds()
    ):
        raise ObserverError("authorization-window-invalid")
    if authorized > current or rule_declared > current:
        raise ObserverError("plan-evidence-future")
    if any(
        (current - value).total_seconds() > policy["maxEvidenceAgeSeconds"]
        for value in (authorized, rule_declared)
    ):
        raise ObserverError("plan-evidence-stale")
    if not allow_expired and not (rehearsal_starts <= current < rehearsal_ends <= expires):
        raise ObserverError("plan-expired")
    if not allow_expired and (current >= removal_deadline or current >= review_ends):
        raise ObserverError("plan-expired")
    if review["lifecycle"] != LIFECYCLE or review["decision"] not in (
        {"approved", "rejected"} if allow_rejected else {"approved"}
    ):
        raise ObserverError("second-review-invalid")
    reviewer = _safe_name(review["reviewer"])
    if reviewer == declaration.get("reviewer"):
        raise ObserverError("reviewers-not-distinct")
    declared = _time(review["declaredAt"])
    if not review_starts <= declared < review_ends:
        raise ObserverError("second-review-window-invalid")
    if declared > current or (current - declared).total_seconds() > policy["maxEvidenceAgeSeconds"]:
        raise ObserverError("second-review-not-fresh")
    if (
        review["planSha256"] != _digest(plan_raw)
        or review["ruleIdentitySha256"] != plan["ruleIdentitySha256"]
    ):
        raise ObserverError("second-review-mismatch")
    if review["retentionSeconds"] != policy["retentionSeconds"]:
        raise ObserverError("retention-mismatch")
    if _time(review["retentionEndsAt"]) != declared + timedelta(seconds=policy["retentionSeconds"]):
        raise ObserverError("retention-mismatch")
    return plan, review


def _signal(plan: dict[str, Any], current: datetime) -> dict[str, Any]:
    auth = plan["authorization"]
    deadline = _time(auth["removalDeadline"])
    return {
        "required": True,
        "urgency": "immediate",
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "owner": auth["removalOwner"],
        "deadline": auth["removalDeadline"],
        "handoff": auth["handoff"],
        "escalation": auth["escalation"],
        "deadlineMissed": current >= deadline,
        "escalationRequired": current >= deadline,
        "observerPerformedCleanup": False,
    }


def _record(
    plan_raw: bytes,
    review_raw: bytes,
    plan: dict[str, Any],
    review: dict[str, Any],
    current: datetime,
    statuses: dict[str, int | None],
    outcome: str,
    reason: str,
) -> dict[str, Any]:
    observation = [
        {"path": path, "observed": statuses[path] is not None, "status": statuses[path]}
        for path in ROUTES
    ]
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceType": "static-429-boundary-observation",
        "lifecycle": LIFECYCLE,
        "observedAt": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome,
        "reason": reason,
        "cleanupState": "cleanup-pending",
        "quotaDrillEvidence": False,
        "originAttributed": False,
        "planSha256": _digest(plan_raw),
        "reviewedConfigurationSha256": plan["reviewedConfigurationSha256"],
        "secondReviewerDeclaration": {
            "reviewer": review["reviewer"],
            "declaredAt": review["declaredAt"],
            "sha256": _digest(review_raw),
            "authenticated": False,
            "independentlyProven": False,
        },
        "evidencePolicy": {
            "freshnessSeconds": plan["policy"]["maxEvidenceAgeSeconds"],
            "retentionSeconds": plan["policy"]["retentionSeconds"],
            "retentionEndsAt": review["retentionEndsAt"],
            "secondReviewDeclaredAt": review["declaredAt"],
            "secondReviewSha256": _digest(review_raw),
        },
        "ruleScopeReviewer": plan["authorization"]["approvedReviewer"],
        "routes": observation,
        "cleanupRequired": _signal(plan, current),
        "cleanupAttestation": None,
    }
    record["observationSha256"] = _digest(_canonical(record))
    return record


def _observation_time(now: datetime | None) -> datetime:
    """Use an injected instant in tests, but a fresh production wall clock."""
    return _now(now) if now is not None else _now(None)


def _validate_observation_record(record: dict[str, Any]) -> None:
    """Validate the canonical pending record before attaching cleanup evidence."""
    _exact(record, RECORD_FIELDS)
    if (
        record["schemaVersion"] != SCHEMA_VERSION
        or record["evidenceType"] != "static-429-boundary-observation"
        or record["lifecycle"] != LIFECYCLE
        or record["outcome"] not in {"success", "failed"}
        or not isinstance(record["reason"], str)
        or record["cleanupState"] != "cleanup-pending"
        or record["cleanupAttestation"] is not None
        or record["quotaDrillEvidence"] is not False
        or record["originAttributed"] is not False
    ):
        raise ObserverError("observation-record-invalid")
    _time(record["observedAt"])
    for field in ("planSha256", "reviewedConfigurationSha256", "observationSha256"):
        if not isinstance(record[field], str) or not SHA256_RE.fullmatch(record[field]):
            raise ObserverError("observation-record-invalid")
    second = _exact(
        record["secondReviewerDeclaration"],
        {"reviewer", "declaredAt", "sha256", "authenticated", "independentlyProven"},
    )
    policy = _exact(
        record["evidencePolicy"],
        {
            "freshnessSeconds",
            "retentionSeconds",
            "retentionEndsAt",
            "secondReviewDeclaredAt",
            "secondReviewSha256",
        },
    )
    if (
        second["authenticated"] is not False
        or second["independentlyProven"] is not False
        or second["declaredAt"] != policy["secondReviewDeclaredAt"]
        or second["sha256"] != policy["secondReviewSha256"]
        or any(
            type(policy[field]) is not int or policy[field] < 1
            for field in ("freshnessSeconds", "retentionSeconds")
        )
    ):
        raise ObserverError("observation-record-invalid")
    _safe_name(second["reviewer"])
    _safe_name(record["ruleScopeReviewer"])
    _time(policy["secondReviewDeclaredAt"])
    _time(policy["retentionEndsAt"])
    if not all(
        isinstance(policy[field], str) and SHA256_RE.fullmatch(policy[field])
        for field in ("secondReviewSha256",)
    ):
        raise ObserverError("observation-record-invalid")
    if not isinstance(record["routes"], list) or len(record["routes"]) != len(ROUTES):
        raise ObserverError("observation-record-invalid")
    for path, route in zip(ROUTES, record["routes"]):
        route = _exact(route, {"path", "observed", "status"})
        if (
            route["path"] != path
            or type(route["observed"]) is not bool
            or (route["status"] is None) != (not route["observed"])
            or (
                route["status"] is not None
                and (type(route["status"]) is not int or not 100 <= route["status"] <= 599)
            )
        ):
            raise ObserverError("observation-record-invalid")
    signal = _exact(
        record["cleanupRequired"],
        {
            "required",
            "urgency",
            "ruleIdentitySha256",
            "owner",
            "deadline",
            "handoff",
            "escalation",
            "deadlineMissed",
            "escalationRequired",
            "observerPerformedCleanup",
        },
    )
    if (
        signal["required"] is not True
        or signal["urgency"] != "immediate"
        or signal["observerPerformedCleanup"] is not False
        or type(signal["deadlineMissed"]) is not bool
        or signal["escalationRequired"] is not signal["deadlineMissed"]
        or not isinstance(signal["ruleIdentitySha256"], str)
        or not SHA256_RE.fullmatch(signal["ruleIdentitySha256"])
    ):
        raise ObserverError("observation-record-invalid")
    for field in ("owner", "handoff", "escalation"):
        _safe_name(signal[field])
    _time(signal["deadline"])


def observe(
    plan_raw: bytes, review_raw: bytes, transport: Transport, *, now: datetime | None = None
) -> dict[str, Any]:
    """Perform the exact one-shot tuple, stopping on the first violation."""
    current = _observation_time(now)
    plan, review = validate_inputs(
        plan_raw, review_raw, now=current, allow_expired=True, allow_rejected=True
    )
    statuses: dict[str, int | None] = dict.fromkeys(ROUTES)
    authorization = plan["authorization"]
    if review["decision"] != "approved":
        return _record(
            plan_raw,
            review_raw,
            plan,
            review,
            current,
            statuses,
            "failed",
            "review-rejected",
        )
    if not (
        _time(authorization["rehearsalStartsAt"])
        <= current
        < min(
            _time(authorization["rehearsalEndsAt"]),
            _time(authorization["reviewEndsAt"]),
            _time(authorization["removalDeadline"]),
            _time(authorization["expiresAt"]),
        )
    ):
        return _record(
            plan_raw,
            review_raw,
            plan,
            review,
            current,
            statuses,
            "failed",
            "authorization-expired",
        )
    outcome, reason = "success", "exact-status-tuple"
    deadline = min(
        _time(authorization["rehearsalEndsAt"]),
        _time(authorization["reviewEndsAt"]),
        _time(authorization["removalDeadline"]),
        _time(authorization["expiresAt"]),
    )
    for path in ROUTES:
        try:
            request_time = _observation_time(now)
            remaining = (deadline - request_time).total_seconds()
            if remaining <= 0:
                outcome, reason = "failed", "authorization-expired"
                break
            status = transport.request(
                method="GET",
                url=f"https://{AUTHORITY}{path}",
                timeout=min(plan["policy"]["timeoutSeconds"], remaining),
                follow_redirects=False,
            )
            if type(status) is not int or not 100 <= status <= 599:
                raise ObserverError("transport-contract")
            statuses[path] = status
            if 300 <= status <= 399:
                outcome, reason = "failed", "redirect-rejected"
                break
            if status != EXPECTED[path]:
                outcome, reason = "failed", "unexpected-status"
                break
        except (KeyboardInterrupt, TimeoutError, ConnectionError, OSError, ObserverError):
            outcome, reason = "failed", "observation-interrupted"
            break
    completed = _observation_time(now)
    if completed >= deadline and outcome == "success":
        outcome, reason = "failed", "authorization-expired"
    return _record(plan_raw, review_raw, plan, review, completed, statuses, outcome, reason)


def abandon(plan_raw: bytes, review_raw: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    """Record a never-started or abandoned run while still requiring cleanup."""
    current = _now(now)
    plan, review = validate_inputs(plan_raw, review_raw, now=current, allow_expired=True)
    return _record(
        plan_raw,
        review_raw,
        plan,
        review,
        current,
        dict.fromkeys(ROUTES),
        "failed",
        "abandoned",
    )


def attest_cleanup(
    record: dict[str, Any], attestation_raw: bytes, proof: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Close cleanup only; never rewrite the immutable observation outcome."""
    current = _now(now)
    try:
        _validate_observation_record(record)
    except ObserverError as exc:
        raise ObserverError("observation-record-invalid") from exc
    claimed_observation = record.get("observationSha256")
    unsigned_record = json.loads(json.dumps(record))
    unsigned_record.pop("observationSha256", None)
    if not isinstance(claimed_observation, str) or claimed_observation != _digest(
        _canonical(unsigned_record)
    ):
        raise ObserverError("observation-record-invalid")
    attestation = _exact(_load(attestation_raw), CLEANUP_FIELDS)
    if attestation["schemaVersion"] != SCHEMA_VERSION or attestation["decision"] != "absent":
        raise ObserverError("cleanup-attestation-invalid")
    if not proof or attestation["cleanupProofSha256"] != _digest(proof):
        raise ObserverError("cleanup-proof-mismatch")
    signal = record.get("cleanupRequired", {})
    if attestation["ruleIdentitySha256"] != signal.get("ruleIdentitySha256"):
        raise ObserverError("cleanup-identity-mismatch")
    reviewer = _safe_name(attestation["reviewer"])
    excluded_reviewers = {
        record.get("ruleScopeReviewer"),
        record.get("secondReviewerDeclaration", {}).get("reviewer"),
        signal.get("owner"),
    }
    if reviewer in excluded_reviewers:
        raise ObserverError("cleanup-review-not-independent")
    declared = _time(attestation["declaredAt"])
    freshness = record.get("evidencePolicy", {}).get("freshnessSeconds")
    if type(freshness) is not int or freshness < 1:
        raise ObserverError("cleanup-policy-invalid")
    if (
        declared < _time(record["observedAt"])
        or declared > current
        or (current - declared).total_seconds() > freshness
    ):
        raise ObserverError("cleanup-proof-not-fresh")
    result = json.loads(json.dumps(record))
    result["cleanupState"] = "cleanup-proven"
    result["cleanupAttestation"] = {
        "reviewer": reviewer,
        "declaredAt": attestation["declaredAt"],
        "ruleIdentitySha256": attestation["ruleIdentitySha256"],
        "cleanupProofSha256": attestation["cleanupProofSha256"],
        "cleanupAttestationSha256": _digest(attestation_raw),
        "authenticated": False,
        "independentlyProven": False,
    }
    return result


def _write_record(path: str, record: dict[str, Any]) -> None:
    encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if path == "-":
        sys.stdout.buffer.write(encoded)
        return
    temporary = f"{path}.tmp.{os.getpid()}"
    try:
        with open(temporary, "xb") as stream:
            stream.write(encoded)
        os.link(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    """Run the standalone observer and emit only redacted evidence or errors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="immutable offline plan JSON")
    parser.add_argument("--review", required=True, help="second-reviewer declaration JSON")
    parser.add_argument("--output", required=True, help="new evidence path, or - for stdout")
    parser.add_argument("--acknowledge-cleanup", action="store_true", required=True)
    parser.add_argument(
        "--abandon", action="store_true", help="record a run without network access"
    )
    args = parser.parse_args(argv)
    try:
        with open(args.plan, "rb") as stream:
            plan_raw = stream.read()
        with open(args.review, "rb") as stream:
            review_raw = stream.read()
        record = (
            abandon(plan_raw, review_raw)
            if args.abandon
            else observe(plan_raw, review_raw, UrllibTransport())
        )
        _write_record(args.output, record)
    except (ObserverError, OSError):
        print("observer-error: operation-failed", file=sys.stderr)
        return 2
    return 0 if record["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
