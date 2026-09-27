#!/usr/bin/env python3
"""Bounded observer for an approved static-429 plan.

This module deliberately has no default network transport and no rule-management
capability.  Callers must inject the single-request transport.  Attestations are
declarations: digest validation binds bytes, but does not authenticate a reviewer
or prove that a declaration is true.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

SCHEMA_VERSION = 1
PLAN_TYPE = "offline-static-429-boundary-emulation"
LIFECYCLE = "authorized-static-emulation"
AUTHORITY = "staging.token.place"
ROUTES = ("/", "/api/v1/meta", "/livez", "/healthz")
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
RULE_REVIEW_FIELDS = {"reviewer", "decision", "declaredAt", "authenticated", "independentlyProven"}
SECOND_REVIEW_FIELDS = {
    "schemaVersion",
    "reviewer",
    "decision",
    "declaredAt",
    "planSha256",
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
OBSERVATION_FIELDS = {
    "schemaVersion",
    "evidenceType",
    "quotaDrillEvidence",
    "originAttributed",
    "observedAt",
    "planSha256",
    "ruleIdentitySha256",
    "reviewedConfigurationSha256",
    "outcome",
    "diagnostic",
    "interrupted",
    "observations",
    "cleanupState",
    "cleanupRequired",
    "evidenceFreshnessSeconds",
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
    """Observer input failed closed without echoing private data."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObserverError("observer input contains a duplicate field")
        result[key] = value
    return result


def load_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except ObserverError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ObserverError(f"{label} must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ObserverError(f"{label} must be an object")
    _privacy_check(value)
    return value


def _privacy_check(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ObserverError("observer input schema mismatch")
            if re.sub(r"[^a-z]", "", key.lower()) in PROHIBITED_KEYS:
                raise ObserverError("observer input contains a prohibited privacy field")
            _privacy_check(child)
    elif isinstance(value, list):
        for child in value:
            _privacy_check(child)


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ObserverError(f"{label} schema mismatch")
    return value


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ObserverError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ObserverError(f"{label} must be a canonical UTC timestamp") from exc
    if (
        parsed.tzinfo != timezone.utc
        or parsed.microsecond
        or value != parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    ):
        raise ObserverError(f"{label} must be a canonical UTC timestamp")
    return parsed


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc).replace(microsecond=0)
    if current.tzinfo != timezone.utc or current.microsecond:
        raise ObserverError("observation time must use whole UTC seconds")
    return current


def _safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", value):
        raise ObserverError(f"{label} must be a bounded named value")
    return value


def _validate_plan(plan: dict[str, Any]) -> None:
    _exact(plan, PLAN_FIELDS, "plan")
    if type(plan["schemaVersion"]) is not int or plan["schemaVersion"] != SCHEMA_VERSION:
        raise ObserverError("unsupported plan schemaVersion")
    if not (
        plan["planType"] == PLAN_TYPE
        and plan["executable"] is False
        and plan["networkCapable"] is False
        and plan["mutationCapable"] is False
        and plan["quotaDrillEvidence"] is False
    ):
        raise ObserverError("plan safety classification mismatch")
    target = _exact(plan["target"], TARGET_FIELDS, "target")
    if target != {
        "scheme": "https",
        "authority": AUTHORITY,
        "method": "GET",
        "emulationPaths": ["/", "/api/v1/meta"],
        "healthControlPaths": ["/livez", "/healthz"],
        "followRedirects": False,
    }:
        raise ObserverError("plan target is not the exact canonical target")
    if plan["expectedStatuses"] != EXPECTED:
        raise ObserverError("plan expected status tuple mismatch")
    authorization = _exact(plan["authorization"], AUTH_FIELDS, "authorization")
    policy = _exact(plan["policy"], POLICY_FIELDS, "policy")
    declaration = _exact(plan["reviewerDeclaration"], RULE_REVIEW_FIELDS, "rule review")
    if authorization["lifecycle"] != LIFECYCLE:
        raise ObserverError("explicit authorized-static-emulation lifecycle is required")
    if (
        declaration["decision"] != "approved"
        or declaration["authenticated"] is not False
        or declaration["independentlyProven"] is not False
    ):
        raise ObserverError("rule review declaration mismatch")
    if declaration["reviewer"] != authorization["approvedReviewer"]:
        raise ObserverError("rule reviewer binding mismatch")
    for digest in (
        plan["inputSha256"],
        plan["ruleIdentitySha256"],
        plan["reviewedConfigurationSha256"],
        authorization["approvedRuleIdentitySha256"],
        authorization["approvedScopeSha256"],
    ):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ObserverError("plan contains an invalid SHA-256 digest")
    if authorization["approvedRuleIdentitySha256"] != plan["ruleIdentitySha256"]:
        raise ObserverError("rule identity binding mismatch")
    for field in POLICY_FIELDS:
        minimum = 0 if field == "maxFutureSkewSeconds" else 1
        if type(policy[field]) is not int or policy[field] < minimum:
            raise ObserverError("plan policy mismatch")
    if (
        policy["maxFutureSkewSeconds"] != 0
        or policy["timeoutSeconds"] > policy["approvedTimeoutSeconds"]
        or policy["retentionSeconds"] > policy["approvedRetentionSeconds"]
    ):
        raise ObserverError("plan policy exceeds approved bounds")
    for field in ("removalOwner", "handoff", "escalation"):
        _safe_name(authorization[field], field)


def validate_inputs(
    plan_raw: bytes, review_raw: bytes, *, now: datetime | None = None
) -> tuple[dict[str, Any], str]:
    """Validate immutable plan bytes and the separate plan-review declaration."""
    plan = load_json(plan_raw, "plan")
    review = load_json(review_raw, "second review")
    _validate_plan(plan)
    _exact(review, SECOND_REVIEW_FIELDS, "second review")
    current = _now(now)
    authorization = plan["authorization"]
    policy = plan["policy"]
    reviewer = _safe_name(review["reviewer"], "second reviewer")
    if review["schemaVersion"] != SCHEMA_VERSION or review["decision"] != "approved":
        raise ObserverError("second review declaration is not approved")
    if reviewer == plan["reviewerDeclaration"]["reviewer"]:
        raise ObserverError("second reviewer must differ from the rule reviewer")
    plan_digest = _digest(plan_raw)
    if review["planSha256"] != plan_digest:
        raise ObserverError("second review does not bind the immutable plan")
    if review["retentionSeconds"] != policy["retentionSeconds"]:
        raise ObserverError("second review retention binding mismatch")
    declared = _timestamp(review["declaredAt"], "second review declaredAt")
    retention_end = _timestamp(review["retentionEndsAt"], "retentionEndsAt")
    if declared > current:
        raise ObserverError("second review is future-dated")
    if (current - declared).total_seconds() > policy["maxEvidenceAgeSeconds"]:
        raise ObserverError("second review is stale")
    expected_retention_end = declared.timestamp() + policy["retentionSeconds"]
    if retention_end.timestamp() != expected_retention_end:
        raise ObserverError("second review retention expiry mismatch")
    starts = _timestamp(authorization["rehearsalStartsAt"], "rehearsalStartsAt")
    ends = _timestamp(authorization["rehearsalEndsAt"], "rehearsalEndsAt")
    expires = _timestamp(authorization["expiresAt"], "expiresAt")
    review_end = _timestamp(authorization["reviewEndsAt"], "reviewEndsAt")
    deadline = _timestamp(authorization["removalDeadline"], "removalDeadline")
    if not starts <= current < min(ends, expires, review_end, deadline):
        raise ObserverError("plan is expired or outside its authorized window")
    return plan, plan_digest


def _cleanup_signal(plan: dict[str, Any], current: datetime) -> dict[str, Any]:
    authorization = plan["authorization"]
    deadline = _timestamp(authorization["removalDeadline"], "removalDeadline")
    return {
        "required": True,
        "performedByObserver": False,
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "owner": authorization["removalOwner"],
        "deadline": authorization["removalDeadline"],
        "handoff": authorization["handoff"],
        "escalation": authorization["escalation"],
        "deadlineMissed": current >= deadline,
        "escalationRequired": current >= deadline,
    }


def observe(
    plan_raw: bytes,
    review_raw: bytes,
    transport: Callable[..., Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Perform at most one injected observation per route, stopping on first violation."""
    current = _now(now)
    plan, plan_digest = validate_inputs(plan_raw, review_raw, now=current)
    observations = [{"path": path, "status": None, "observed": False} for path in ROUTES]
    outcome = "failed"
    diagnostic = "observation-incomplete"
    interrupted = False
    for index, path in enumerate(ROUTES):
        try:
            response = transport(
                method="GET",
                url=f"https://{AUTHORITY}{path}",
                timeout=plan["policy"]["timeoutSeconds"],
                follow_redirects=False,
            )
            status = response if type(response) is int else getattr(response, "status", None)
            redirected = False if type(response) is int else getattr(response, "redirected", None)
            if type(status) is not int or type(redirected) is not bool:
                diagnostic = "transport-contract-violation"
                break
            observations[index] = {"path": path, "status": status, "observed": True}
            if redirected or 300 <= status < 400:
                diagnostic = "redirect-refused"
                break
            if status != EXPECTED[path]:
                diagnostic = "unexpected-status"
                break
        except (KeyboardInterrupt, SystemExit):
            diagnostic = "observation-interrupted"
            interrupted = True
            break
        except Exception:
            diagnostic = "transport-failure"
            break
    else:
        outcome = "success"
        diagnostic = "exact-status-tuple-observed"
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceType": "static-429-boundary-observation",
        "quotaDrillEvidence": False,
        "originAttributed": False,
        "observedAt": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "planSha256": plan_digest,
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "reviewedConfigurationSha256": plan["reviewedConfigurationSha256"],
        "outcome": outcome,
        "diagnostic": diagnostic,
        "interrupted": interrupted,
        "observations": observations,
        "cleanupState": "cleanup-pending",
        "cleanupRequired": _cleanup_signal(plan, current),
        "evidenceFreshnessSeconds": plan["policy"]["maxEvidenceAgeSeconds"],
    }
    record["observationSha256"] = _digest(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    )
    return record


def abandon(plan_raw: bytes, review_raw: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    """Record a valid, never-started plan as abandoned and cleanup-pending."""
    current = _now(now)
    plan, plan_digest = validate_inputs(plan_raw, review_raw, now=current)
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceType": "static-429-boundary-observation",
        "quotaDrillEvidence": False,
        "originAttributed": False,
        "observedAt": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "planSha256": plan_digest,
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "reviewedConfigurationSha256": plan["reviewedConfigurationSha256"],
        "outcome": "failed",
        "diagnostic": "observation-abandoned",
        "interrupted": False,
        "observations": [{"path": path, "status": None, "observed": False} for path in ROUTES],
        "cleanupState": "cleanup-pending",
        "cleanupRequired": _cleanup_signal(plan, current),
        "evidenceFreshnessSeconds": plan["policy"]["maxEvidenceAgeSeconds"],
    }
    record["observationSha256"] = _digest(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    )
    return record


def apply_cleanup(
    record: dict[str, Any], cleanup_raw: bytes, proof_bytes: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Close cleanup using fresh identity-bound absence evidence; never alter outcome."""
    current = _now(now)
    _exact(record, OBSERVATION_FIELDS, "observation evidence")
    _privacy_check(record)
    bound_record = {key: value for key, value in record.items() if key != "observationSha256"}
    if record["observationSha256"] != _digest(
        json.dumps(bound_record, sort_keys=True, separators=(",", ":")).encode()
    ):
        raise ObserverError("observation evidence digest mismatch")
    cleanup = load_json(cleanup_raw, "cleanup declaration")
    _exact(cleanup, CLEANUP_FIELDS, "cleanup declaration")
    if cleanup["schemaVersion"] != SCHEMA_VERSION or cleanup["decision"] != "rule-absent":
        raise ObserverError("cleanup declaration does not prove absence")
    reviewer = _safe_name(cleanup["reviewer"], "cleanup reviewer")
    if reviewer in {record["cleanupRequired"]["owner"]}:
        raise ObserverError("cleanup reviewer must differ from the removal owner")
    if cleanup["ruleIdentitySha256"] != record["ruleIdentitySha256"]:
        raise ObserverError("cleanup rule identity mismatch")
    if not proof_bytes or cleanup["cleanupProofSha256"] != _digest(proof_bytes):
        raise ObserverError("cleanup proof digest mismatch")
    declared = _timestamp(cleanup["declaredAt"], "cleanup declaredAt")
    if declared > current:
        raise ObserverError("cleanup declaration is future-dated")
    if (
        type(record["evidenceFreshnessSeconds"]) is not int
        or record["evidenceFreshnessSeconds"] < 1
    ):
        raise ObserverError("observation evidence freshness mismatch")
    if (current - declared).total_seconds() > record["evidenceFreshnessSeconds"]:
        raise ObserverError("cleanup declaration is stale")
    # The plan's approved evidence age remains available in the immutable plan only;
    # require cleanup at the supplied observation/removal deadline boundary.
    deadline = _timestamp(record["cleanupRequired"]["deadline"], "cleanup deadline")
    if declared < _timestamp(record["observedAt"], "observedAt"):
        raise ObserverError("cleanup declaration predates observation")
    updated = json.loads(json.dumps(record))
    updated["cleanupState"] = "cleanup-proven"
    updated["cleanupAttestation"] = {
        "reviewer": reviewer,
        "declaredAt": cleanup["declaredAt"],
        "ruleIdentitySha256": cleanup["ruleIdentitySha256"],
        "cleanupProofSha256": cleanup["cleanupProofSha256"],
        "authenticated": False,
        "independentlyProven": False,
        "deadlineMissed": declared > deadline,
    }
    updated["cleanupSha256"] = _digest(cleanup_raw + b"\0" + proof_bytes)
    return updated
