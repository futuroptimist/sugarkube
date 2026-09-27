#!/usr/bin/env python3
"""Bounded observer for an approved, pre-existing static-429 staging rule.

The observer can only issue four fixed GET requests.  It deliberately has no rule
management or cleanup capability; attestations accepted here are declarations.
"""

from __future__ import annotations

import hashlib
import json
import re
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
    def request(self, *, method: str, url: str, timeout: int, follow_redirects: bool) -> int:
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

    def request(self, *, method: str, url: str, timeout: int, follow_redirects: bool) -> int:
        if method != "GET" or follow_redirects:
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


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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
    if isinstance(value, dict):
        for key, child in value.items():
            if re.sub(r"[^a-z]", "", key.lower()) in PROHIBITED_KEYS:
                raise ObserverError("privacy-field")
            _privacy(child)
    elif isinstance(value, list):
        for child in value:
            _privacy(child)


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
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", value):
        raise ObserverError("named-value-invalid")
    return value


def validate_inputs(
    plan_raw: bytes, review_raw: bytes, *, now: datetime | None = None
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
    if authorization.get("approvedRuleIdentitySha256") != plan["ruleIdentitySha256"]:
        raise ObserverError("rule-identity-mismatch")
    if type(policy.get("timeoutSeconds")) is not int or policy["timeoutSeconds"] < 1:
        raise ObserverError("timeout-invalid")
    if type(policy.get("retentionSeconds")) is not int or policy["retentionSeconds"] < 1:
        raise ObserverError("retention-invalid")
    for field in ("maxEvidenceAgeSeconds", "approvedEvidenceAgeSeconds"):
        if type(policy.get(field)) is not int or policy[field] < 1:
            raise ObserverError("freshness-invalid")
    if policy["maxEvidenceAgeSeconds"] > policy["approvedEvidenceAgeSeconds"]:
        raise ObserverError("freshness-invalid")
    if (
        policy["maxFutureSkewSeconds"] != 0
        or policy["timeoutSeconds"] > policy["approvedTimeoutSeconds"]
        or policy["retentionSeconds"] > policy["approvedRetentionSeconds"]
    ):
        raise ObserverError("policy-drift")
    authorized = _time(authorization["authorizedAt"])
    rule_declared = _time(declaration["declaredAt"])
    if authorized > current or rule_declared > current:
        raise ObserverError("plan-evidence-future")
    if any(
        (current - value).total_seconds() > policy["maxEvidenceAgeSeconds"]
        for value in (authorized, rule_declared)
    ):
        raise ObserverError("plan-evidence-stale")
    if not (
        _time(authorization["rehearsalStartsAt"])
        <= current
        < _time(authorization["rehearsalEndsAt"])
        <= _time(authorization["expiresAt"])
    ):
        raise ObserverError("plan-expired")
    if current >= _time(authorization["removalDeadline"]) or current >= _time(
        authorization["reviewEndsAt"]
    ):
        raise ObserverError("plan-expired")
    if review["lifecycle"] != LIFECYCLE or review["decision"] != "approved":
        raise ObserverError("second-review-invalid")
    reviewer = _safe_name(review["reviewer"])
    if reviewer == declaration.get("reviewer"):
        raise ObserverError("reviewers-not-distinct")
    declared = _time(review["declaredAt"])
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
    observation_raw = json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()
    return {
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
        "observationSha256": _digest(observation_raw),
        "secondReviewerDeclaration": {
            "reviewer": review["reviewer"],
            "authenticated": False,
            "independentlyProven": False,
        },
        "evidencePolicy": {
            "freshnessSeconds": plan["policy"]["maxEvidenceAgeSeconds"],
            "retentionSeconds": plan["policy"]["retentionSeconds"],
            "retentionEndsAt": review["retentionEndsAt"],
        },
        "routes": observation,
        "cleanupRequired": _signal(plan, current),
        "cleanupAttestation": None,
    }


def observe(
    plan_raw: bytes, review_raw: bytes, transport: Transport, *, now: datetime | None = None
) -> dict[str, Any]:
    """Perform the exact one-shot tuple, stopping on the first violation."""
    current = _now(now)
    plan, review = validate_inputs(plan_raw, review_raw, now=current)
    statuses: dict[str, int | None] = dict.fromkeys(ROUTES)
    outcome, reason = "success", "exact-status-tuple"
    for path in ROUTES:
        try:
            status = transport.request(
                method="GET",
                url=f"https://{AUTHORITY}{path}",
                timeout=plan["policy"]["timeoutSeconds"],
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
    return _record(plan_raw, plan, review, current, statuses, outcome, reason)


def abandon(plan_raw: bytes, review_raw: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    """Record a never-started or abandoned run while still requiring cleanup."""
    current = _now(now)
    plan, review = validate_inputs(plan_raw, review_raw, now=current)
    return _record(plan_raw, plan, review, current, dict.fromkeys(ROUTES), "failed", "abandoned")


def attest_cleanup(
    record: dict[str, Any], attestation_raw: bytes, proof: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Close cleanup only; never rewrite the immutable observation outcome."""
    current = _now(now)
    attestation = _exact(_load(attestation_raw), CLEANUP_FIELDS)
    if attestation["schemaVersion"] != SCHEMA_VERSION or attestation["decision"] != "absent":
        raise ObserverError("cleanup-attestation-invalid")
    if not proof or attestation["cleanupProofSha256"] != _digest(proof):
        raise ObserverError("cleanup-proof-mismatch")
    signal = record.get("cleanupRequired", {})
    if attestation["ruleIdentitySha256"] != signal.get("ruleIdentitySha256"):
        raise ObserverError("cleanup-identity-mismatch")
    reviewer = _safe_name(attestation["reviewer"])
    if reviewer == record.get("secondReviewerDeclaration", {}).get("reviewer"):
        raise ObserverError("cleanup-review-not-independent")
    declared = _time(attestation["declaredAt"])
    freshness = record.get("evidencePolicy", {}).get("freshnessSeconds")
    if type(freshness) is not int or freshness < 1:
        raise ObserverError("cleanup-policy-invalid")
    if declared > current or (current - declared).total_seconds() > freshness:
        raise ObserverError("cleanup-proof-not-fresh")
    result = json.loads(json.dumps(record))
    result["cleanupState"] = "cleanup-proven"
    result["cleanupAttestation"] = {
        "reviewer": reviewer,
        "declaredAt": attestation["declaredAt"],
        "ruleIdentitySha256": attestation["ruleIdentitySha256"],
        "cleanupProofSha256": attestation["cleanupProofSha256"],
        "authenticated": False,
        "independentlyProven": False,
    }
    return result
