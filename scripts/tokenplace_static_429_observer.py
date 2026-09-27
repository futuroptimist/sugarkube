#!/usr/bin/env python3
"""Bounded observer for an already-authorized static-429 staging plan.

The transport is supplied by the caller.  This module has no rule-management,
cluster, registry, or application-mutation capability.  Attestations are recorded
as declarations; their truth and reviewer independence are not authenticated here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from scripts import tokenplace_static_429_plan as planner

SCHEMA_VERSION = 1
ROUTES = planner.ROUTES
EXPECTED = {"/": 429, "/api/v1/meta": 429, "/livez": 200, "/healthz": 200}
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
REVIEW_FIELDS = {
    "schemaVersion",
    "lifecycle",
    "reviewer",
    "decision",
    "declaredAt",
    "planSha256",
    "ruleIdentitySha256",
    "retentionSeconds",
    "retentionExpiresAt",
}
CLEANUP_FIELDS = {
    "schemaVersion",
    "decision",
    "reviewer",
    "declaredAt",
    "ruleIdentitySha256",
    "cleanupProofSha256",
    "ruleAbsent",
}


class ObserverError(ValueError):
    """Observer input failed closed without disclosing caller-controlled data."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _load(raw: bytes, fields: set[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=planner._pairs)
        planner._privacy_check(value)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, planner.PlanError) as exc:
        raise ObserverError(f"{label} refused") from exc
    if not isinstance(value, dict) or set(value) != fields:
        raise ObserverError(f"{label} refused")
    return value


def _time(value: Any, label: str) -> datetime:
    try:
        return planner._timestamp(value, label)
    except planner.PlanError as exc:
        raise ObserverError(f"{label} refused") from exc


def _validate_plan(plan: dict[str, Any], now: datetime) -> None:
    if plan.get("schemaVersion") != 1 or set(plan) != PLAN_FIELDS:
        raise ObserverError("plan refused")
    if (
        plan["planType"] != "offline-static-429-boundary-emulation"
        or plan["executable"] is not False
        or plan["networkCapable"] is not False
        or plan["mutationCapable"] is not False
        or plan["quotaDrillEvidence"] is not False
    ):
        raise ObserverError("plan refused")
    try:
        planner._validate_scope(plan["target"], "target")
        planner._exact(plan["authorization"], planner.AUTH_FIELDS, "authorization")
        planner._exact(plan["policy"], planner.POLICY_FIELDS, "policy")
        reviewer = planner._exact(
            plan["reviewerDeclaration"],
            {"reviewer", "decision", "declaredAt", "authenticated", "independentlyProven"},
            "reviewerDeclaration",
        )
    except (KeyError, TypeError, planner.PlanError) as exc:
        raise ObserverError("plan refused") from exc
    auth = plan["authorization"]
    policy = plan["policy"]
    if (
        auth["lifecycle"] != planner.LIFECYCLE
        or plan["expectedStatuses"] != EXPECTED
        or auth["approvedRuleIdentitySha256"] != plan["ruleIdentitySha256"]
        or auth["approvedReviewer"] != reviewer["reviewer"]
        or reviewer["decision"] != "approved"
        or reviewer["authenticated"] is not False
        or reviewer["independentlyProven"] is not False
    ):
        raise ObserverError("plan refused")
    if now.tzinfo != timezone.utc or now.microsecond:
        raise ObserverError("validation time refused")
    declared = _time(reviewer["declaredAt"], "review declaration")
    authorized = _time(auth["authorizedAt"], "authorization")
    rehearsal_start = _time(auth["rehearsalStartsAt"], "rehearsal start")
    rehearsal_end = _time(auth["rehearsalEndsAt"], "rehearsal end")
    review_end = _time(auth["reviewEndsAt"], "review end")
    expires = _time(auth["expiresAt"], "authorization expiry")
    if not rehearsal_start <= now < min(rehearsal_end, review_end, expires):
        raise ObserverError("plan expired")
    if declared > now or authorized > now:
        raise ObserverError("plan evidence refused")
    if any(
        (now - value).total_seconds() > policy["maxEvidenceAgeSeconds"]
        for value in (declared, authorized)
    ):
        raise ObserverError("plan evidence refused")
    if type(policy["timeoutSeconds"]) is not int or policy["timeoutSeconds"] <= 0:
        raise ObserverError("plan refused")


def _validate_review(
    raw: bytes, plan: dict[str, Any], plan_digest: str, now: datetime
) -> dict[str, Any]:
    review = _load(raw, REVIEW_FIELDS, "review")
    policy = plan["policy"]
    if (
        type(review["schemaVersion"]) is not int
        or review["schemaVersion"] != SCHEMA_VERSION
        or review["lifecycle"] != planner.LIFECYCLE
        or review["decision"] != "approved"
        or review["planSha256"] != plan_digest
        or review["ruleIdentitySha256"] != plan["ruleIdentitySha256"]
        or review["retentionSeconds"] != policy["retentionSeconds"]
    ):
        raise ObserverError("review refused")
    try:
        planner._safe_text(review["reviewer"], "reviewer")
    except planner.PlanError as exc:
        raise ObserverError("review refused") from exc
    if review["reviewer"] == plan["reviewerDeclaration"]["reviewer"]:
        raise ObserverError("review refused")
    declared = _time(review["declaredAt"], "review declaration")
    retention_expiry = _time(review["retentionExpiresAt"], "retention expiry")
    if declared > now or (now - declared).total_seconds() > policy["maxEvidenceAgeSeconds"]:
        raise ObserverError("review evidence refused")
    if retention_expiry != declared + timedelta(seconds=policy["retentionSeconds"]):
        raise ObserverError("review retention refused")
    return review


def _cleanup_signal(plan: dict[str, Any], now: datetime) -> dict[str, Any]:
    auth = plan["authorization"]
    deadline = _time(auth["removalDeadline"], "removal deadline")
    return {
        "required": True,
        "immediate": True,
        "state": "cleanup-pending",
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "owner": auth["removalOwner"],
        "deadline": auth["removalDeadline"],
        "handoff": auth["handoff"],
        "escalation": auth["escalation"],
        "deadlineMissed": now >= deadline,
        "escalationRequired": now >= deadline,
        "observerPerformedRemoval": False,
    }


def observe(
    plan_bytes: bytes,
    review_bytes: bytes,
    transport: Callable[..., Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Perform at most one exact request per route and return privacy-safe evidence."""
    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    plan = _load(plan_bytes, PLAN_FIELDS, "plan")
    _validate_plan(plan, current)
    plan_digest = _digest(plan_bytes)
    review = _validate_review(review_bytes, plan, plan_digest, current)
    statuses: dict[str, int | None] = {route: None for route in ROUTES}
    outcome = "failed"
    diagnostic = "observation-failed"
    try:
        for route in ROUTES:
            try:
                response = transport(
                    method="GET",
                    url=f"https://{planner.AUTHORITY}{route}",
                    timeout=plan["policy"]["timeoutSeconds"],
                    follow_redirects=False,
                )
            except (KeyboardInterrupt, SystemExit):
                diagnostic = "observation-interrupted"
                break
            except BaseException:
                diagnostic = "transport-failed"
                break
            if type(response) is int:
                status, redirected = response, False
            elif isinstance(response, dict) and set(response) == {"status", "redirected"}:
                status, redirected = response["status"], response["redirected"]
            else:
                diagnostic = "transport-contract-failed"
                break
            if type(status) is not int or type(redirected) is not bool:
                diagnostic = "transport-contract-failed"
                break
            statuses[route] = status
            if redirected:
                diagnostic = "redirect-refused"
                break
            if status != EXPECTED[route]:
                diagnostic = "unexpected-status"
                break
        else:
            outcome, diagnostic = "succeeded", "expected-status-tuple-observed"
    finally:
        cleanup = _cleanup_signal(plan, current)
    observation = {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceType": "static-429-boundary-observation",
        "observedAt": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome,
        "diagnostic": diagnostic,
        "statuses": statuses,
        "quotaDrillEvidence": False,
        "originAttributed": False,
    }
    observation_bytes = json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()
    return {
        **observation,
        "planSha256": plan_digest,
        "reviewDeclarationSha256": _digest(review_bytes),
        "reviewerDeclaration": {"reviewer": review["reviewer"], "authenticated": False},
        "ruleScopeReviewerDeclaration": {
            "reviewer": plan["reviewerDeclaration"]["reviewer"],
            "authenticated": False,
        },
        "ruleIdentitySha256": plan["ruleIdentitySha256"],
        "reviewedConfigurationSha256": plan["reviewedConfigurationSha256"],
        "observationSha256": _digest(observation_bytes),
        "cleanupFreshnessSeconds": plan["policy"]["maxEvidenceAgeSeconds"],
        "cleanup": cleanup,
    }


def abandon(plan_bytes: bytes, *, now: datetime | None = None) -> dict[str, Any]:
    """Return the mandatory cleanup signal when an observation never starts."""
    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    plan = _load(plan_bytes, PLAN_FIELDS, "plan")
    # Deliberately validate structure/scope but allow lifecycle expiry to signal cleanup.
    try:
        planner._validate_scope(plan["target"], "target")
    except (KeyError, planner.PlanError) as exc:
        raise ObserverError("plan refused") from exc
    return {"outcome": "abandoned", "cleanup": _cleanup_signal(plan, current)}


def apply_cleanup(
    evidence: dict[str, Any], cleanup_bytes: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Close only the cleanup obligation using a fresh same-identity declaration."""
    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    cleanup = _load(cleanup_bytes, CLEANUP_FIELDS, "cleanup attestation")
    if (
        cleanup["schemaVersion"] != SCHEMA_VERSION
        or cleanup["decision"] != "absent"
        or cleanup["ruleAbsent"] is not True
        or cleanup["ruleIdentitySha256"] != evidence.get("ruleIdentitySha256")
        or cleanup["reviewer"] == evidence.get("reviewerDeclaration", {}).get("reviewer")
        or cleanup["reviewer"] == evidence.get("ruleScopeReviewerDeclaration", {}).get("reviewer")
        or not planner.SHA256_RE.fullmatch(str(cleanup["cleanupProofSha256"]))
    ):
        raise ObserverError("cleanup attestation refused")
    declared = _time(cleanup["declaredAt"], "cleanup declaration")
    freshness = evidence.get("cleanupFreshnessSeconds")
    if type(freshness) is not int or freshness <= 0:
        raise ObserverError("cleanup attestation refused")
    if declared > current or (current - declared).total_seconds() > freshness:
        raise ObserverError("cleanup attestation refused")
    result = json.loads(json.dumps(evidence))
    result["cleanup"].update(
        {"state": "cleanup-proven", "attestationSha256": _digest(cleanup_bytes)}
    )
    return result
