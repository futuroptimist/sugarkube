#!/usr/bin/env python3
"""Bounded observer for an already-authorized static-429 plan.

The observer can only read an immutable planner output and a second-review
declaration.  Rule management and cleanup remain human-owned operations.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA_VERSION = 1
AUTHORITY = "staging.token.place"
ROUTES = ("/", "/api/v1/meta", "/livez", "/healthz")
EXPECTED = (429, 429, 200, 200)
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
REVIEW_FIELDS = {
    "schemaVersion",
    "decision",
    "reviewer",
    "declaredAt",
    "planSha256",
    "retentionSeconds",
    "retentionEndsAt",
}
CLEANUP_FIELDS = {
    "schemaVersion",
    "decision",
    "reviewer",
    "declaredAt",
    "ruleIdentitySha256",
    "observationSha256",
    "absenceProofSha256",
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
    """A fixed, privacy-safe refusal with optional cleanup evidence."""

    def __init__(self, code: str, evidence: dict[str, Any] | None = None):
        super().__init__(f"observation refused: {code}")
        self.code = code
        self.evidence = evidence


@dataclass(frozen=True)
class TransportResult:
    status: int
    redirected: bool = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def https_transport(method: str, url: str, timeout: int, follow_redirects: bool) -> TransportResult:
    """Perform one HTTPS request; callers must supply the validated exact URL."""
    if follow_redirects:
        raise ValueError("redirect following is prohibited")
    request = urllib.request.Request(url, method=method)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
            return TransportResult(response.status, False)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return TransportResult(exc.code, True)
        return TransportResult(exc.code, False)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObserverError("malformed-input")
        result[key] = value
    return result


def _load(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except ObserverError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ObserverError("malformed-input") from exc
    if not isinstance(value, dict):
        raise ObserverError("malformed-input")
    try:
        _privacy(value)
    except RecursionError as exc:
        raise ObserverError("malformed-input") from exc
    return value


def _privacy(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if normalized in PROHIBITED_KEYS:
                raise ObserverError("privacy-field")
            _privacy(child)
    elif isinstance(value, list):
        for child in value:
            _privacy(child)


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ObserverError("invalid-timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ObserverError("invalid-timestamp") from exc
    if (
        parsed.tzinfo != timezone.utc
        or parsed.microsecond
        or value != parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    ):
        raise ObserverError("invalid-timestamp")
    return parsed


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc).replace(microsecond=0)
    if current.tzinfo != timezone.utc or current.microsecond:
        raise ObserverError("invalid-clock")
    return current


def _exact(value: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ObserverError("schema-mismatch")
    return value


def _safe_name(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and 0 < len(value) <= 80
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", value)
    )


def _validate_plan(plan: dict[str, Any]) -> None:
    _exact(plan, PLAN_FIELDS)
    if plan["schemaVersion"] != 1 or plan["planType"] != "offline-static-429-boundary-emulation":
        raise ObserverError("invalid-plan")
    if (
        plan["executable"],
        plan["networkCapable"],
        plan["mutationCapable"],
        plan["quotaDrillEvidence"],
    ) != (False, False, False, False):
        raise ObserverError("invalid-plan")
    for field in ("inputSha256", "ruleIdentitySha256", "reviewedConfigurationSha256"):
        if not isinstance(plan[field], str) or not SHA256_RE.fullmatch(plan[field]):
            raise ObserverError("invalid-plan")
    target = _exact(plan["target"], TARGET_FIELDS)
    if target != {
        "scheme": "https",
        "authority": AUTHORITY,
        "method": "GET",
        "emulationPaths": ["/", "/api/v1/meta"],
        "healthControlPaths": ["/livez", "/healthz"],
        "followRedirects": False,
    }:
        raise ObserverError("target-drift")
    if plan["expectedStatuses"] != dict(zip(ROUTES, EXPECTED)):
        raise ObserverError("status-contract-drift")
    authorization = plan["authorization"]
    policy = plan["policy"]
    reviewer = plan["reviewerDeclaration"]
    if (
        not isinstance(authorization, dict)
        or authorization.get("lifecycle") != "authorized-static-emulation"
    ):
        raise ObserverError("lifecycle-mismatch")
    if (
        not isinstance(policy, dict)
        or type(policy.get("timeoutSeconds")) is not int
        or policy["timeoutSeconds"] <= 0
    ):
        raise ObserverError("invalid-policy")
    if (
        type(policy.get("retentionSeconds")) is not int
        or type(policy.get("maxEvidenceAgeSeconds")) is not int
    ):
        raise ObserverError("invalid-policy")
    if (
        not isinstance(reviewer, dict)
        or reviewer.get("decision") != "approved"
        or reviewer.get("authenticated") is not False
        or reviewer.get("independentlyProven") is not False
    ):
        raise ObserverError("invalid-rule-review")


def _cleanup_signal(plan: dict[str, Any], current: datetime) -> dict[str, Any]:
    auth = plan["authorization"]
    deadline = auth.get("removalDeadline")
    missed = False
    try:
        missed = current >= _timestamp(deadline)
    except ObserverError:
        missed = True
    return {
        "required": True,
        "state": "cleanup-pending",
        "ruleIdentitySha256": plan.get("ruleIdentitySha256"),
        "owner": auth.get("removalOwner"),
        "deadline": deadline,
        "escalation": auth.get("escalation"),
        "deadlineMissed": missed,
        "ownerMustRemoveImmediately": True,
        "observerPerformedRemoval": False,
    }


def _initial_evidence(plan: dict[str, Any], plan_raw: bytes, current: datetime) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceType": "static-429-boundary-observation",
        "planSha256": _digest(plan_raw),
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "reviewedConfigurationSha256": plan["reviewedConfigurationSha256"],
        "observedAt": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ruleScopeReviewer": plan["reviewerDeclaration"]["reviewer"],
        "cleanupFreshnessSeconds": plan["policy"]["maxEvidenceAgeSeconds"],
        "outcome": "failed",
        "reason": "not-started",
        "routes": [{"path": path, "observed": False, "status": None} for path in ROUTES],
        "cleanup": _cleanup_signal(plan, current),
        "quotaDrillEvidence": False,
        "originAttributed": False,
    }


def observe(
    plan_raw: bytes,
    second_review_raw: bytes,
    transport: Callable[[str, str, int, bool], TransportResult],
    *,
    now: datetime | None = None,
    abandon: bool = False,
) -> dict[str, Any]:
    """Validate authorization and make no more than one request per exact route."""
    current = _now(now)
    plan = _load(plan_raw)
    _validate_plan(plan)
    evidence = _initial_evidence(plan, plan_raw, current)
    try:
        review = _exact(_load(second_review_raw), REVIEW_FIELDS)
        if review["schemaVersion"] != 1 or review["decision"] != "approved":
            raise ObserverError("second-review-refused", evidence)
        if not _safe_name(review["reviewer"]):
            raise ObserverError("second-review-refused", evidence)
        if review["reviewer"] == plan["reviewerDeclaration"]["reviewer"]:
            raise ObserverError("reviewers-must-differ", evidence)
        if review["planSha256"] != _digest(plan_raw):
            raise ObserverError("plan-review-mismatch", evidence)
        if review["retentionSeconds"] != plan["policy"]["retentionSeconds"]:
            raise ObserverError("retention-review-mismatch", evidence)
        evidence["secondReviewer"] = review["reviewer"]
        declared = _timestamp(review["declaredAt"])
        retention_end = _timestamp(review["retentionEndsAt"])
        if declared > current:
            raise ObserverError("future-review", evidence)
        if (current - declared).total_seconds() > plan["policy"]["maxEvidenceAgeSeconds"]:
            raise ObserverError("stale-review", evidence)
        if (retention_end - declared).total_seconds() != review["retentionSeconds"]:
            raise ObserverError("retention-review-mismatch", evidence)
        auth = plan["authorization"]
        if current >= _timestamp(auth["expiresAt"]) or current >= _timestamp(
            auth["rehearsalEndsAt"]
        ):
            raise ObserverError("plan-expired", evidence)
        if current < _timestamp(auth["rehearsalStartsAt"]):
            raise ObserverError("plan-not-active", evidence)
        if abandon:
            evidence["reason"] = "abandoned"
            raise ObserverError("abandoned", evidence)

        timeout = plan["policy"]["timeoutSeconds"]
        for index, (path, expected) in enumerate(zip(ROUTES, EXPECTED)):
            try:
                result = transport("GET", f"https://{AUTHORITY}{path}", timeout, False)
            except KeyboardInterrupt:
                evidence["reason"] = "interrupted"
                raise ObserverError("interrupted", evidence) from None
            except (TimeoutError, socket.timeout):
                evidence["reason"] = "timeout"
                raise ObserverError("timeout", evidence) from None
            except (ssl.SSLError, socket.gaierror, OSError):
                evidence["reason"] = "transport-failure"
                raise ObserverError("transport-failure", evidence) from None
            if not isinstance(result, TransportResult) or type(result.status) is not int:
                evidence["reason"] = "transport-contract"
                raise ObserverError("transport-contract", evidence)
            evidence["routes"][index] = {"path": path, "observed": True, "status": result.status}
            if result.redirected or 300 <= result.status < 400:
                evidence["reason"] = "redirect"
                raise ObserverError("redirect", evidence)
            if result.status != expected:
                evidence["reason"] = "unexpected-status"
                raise ObserverError("unexpected-status", evidence)
        evidence["outcome"] = "success"
        evidence["reason"] = "exact-status-tuple-observed"
        return evidence
    except ObserverError as exc:
        if exc.evidence is None:
            exc.evidence = evidence
        raise


def observation_digest(evidence: dict[str, Any]) -> str:
    """Bind the canonical observation bytes used by a cleanup declaration."""
    return _digest(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())


def apply_cleanup(
    evidence: dict[str, Any], cleanup_raw: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Close cleanup only with fresh, identity-bound declared absence evidence."""
    current = _now(now)
    result = json.loads(json.dumps(evidence))
    cleanup = _exact(_load(cleanup_raw), CLEANUP_FIELDS)
    if cleanup["schemaVersion"] != 1 or cleanup["decision"] != "absent":
        raise ObserverError("cleanup-refused", result)
    if not _safe_name(cleanup["reviewer"]):
        raise ObserverError("cleanup-refused", result)
    if cleanup["ruleIdentitySha256"] != result["ruleIdentitySha256"]:
        raise ObserverError("cleanup-identity-mismatch", result)
    if cleanup["observationSha256"] != observation_digest(evidence):
        raise ObserverError("cleanup-observation-mismatch", result)
    if not isinstance(cleanup["absenceProofSha256"], str) or not SHA256_RE.fullmatch(
        cleanup["absenceProofSha256"]
    ):
        raise ObserverError("cleanup-proof-invalid", result)
    declared = _timestamp(cleanup["declaredAt"])
    if declared > current or declared <= _timestamp(result["observedAt"]):
        raise ObserverError("cleanup-not-fresh", result)
    if cleanup["reviewer"] in {
        result["cleanup"].get("owner"),
        result.get("ruleScopeReviewer"),
        result.get("secondReviewer"),
    }:
        raise ObserverError("cleanup-not-independent", result)
    if (current - declared).total_seconds() > result["cleanupFreshnessSeconds"]:
        raise ObserverError("cleanup-not-fresh", result)
    result["cleanup"].update(
        {
            "state": "cleanup-proven",
            "declaredAt": cleanup["declaredAt"],
            "reviewer": cleanup["reviewer"],
            "absenceProofSha256": cleanup["absenceProofSha256"],
            "cleanupAttestationSha256": _digest(cleanup_raw),
        }
    )
    return result
