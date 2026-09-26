#!/usr/bin/env python3
"""Build an immutable, offline plan for static 429 boundary emulation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """The local planning contract was not satisfied."""


SCHEMA_VERSION = 1
LIFECYCLE = "authorized-static-emulation"
AUTHORITY = "staging.token.place"
EMULATION_ROUTES = (("GET", "/", 429), ("GET", "/api/v1/meta", 429))
HEALTH_CONTROLS = (("GET", "/livez", 200), ("GET", "/healthz", 200))
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._@+-]{0,127}\Z")
PROHIBITED_KEY_PARTS = (
    "credential",
    "cookie",
    "token",
    "pass" "word",
    "secret",
    "body",
    "request_id",
    "caller",
    "raw",
    "query",
    "header",
    "prompt",
    "response",
    "ciphertext",
    "error",
    "private_url",
    "signature",
)

TOP_FIELDS = {
    "schema_version",
    "lifecycle",
    "target",
    "rule_attestation",
    "authorization",
    "policy",
    "created_at",
}
TARGET_FIELDS = {"scheme", "authority", "emulation_routes", "health_controls", "follow_redirects"}
ROUTE_FIELDS = {"method", "path", "expected_status"}
RULE_FIELDS = {
    "attested_at",
    "reviewer",
    "reviewer_decision",
    "rule_identity_sha256",
    "reviewed_configuration_sha256",
    "scope_authority",
    "scope_methods",
    "scope_paths",
}
AUTH_FIELDS = {
    "authorized_at",
    "authorizer",
    "rehearsal_starts_at",
    "rehearsal_ends_at",
    "review_ends_at",
    "expires_at",
    "removal_deadline_at",
    "removal_owner",
    "handoff",
    "escalation",
}
POLICY_FIELDS = {
    "max_evidence_age_seconds",
    "max_future_skew_seconds",
    "max_rehearsal_seconds",
    "max_review_seconds",
    "max_retention_seconds",
    "request_timeout_seconds",
    "retention_seconds",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _exact(value: Any, fields: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{where} must be an object")
    missing, extra = fields - value.keys(), value.keys() - fields
    if missing or extra:
        raise PlanError(
            f"{where} fields are not exact (missing={sorted(missing)}, unknown={sorted(extra)})"
        )
    return value


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PlanError(f"{field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PlanError(f"{field} is malformed") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise PlanError(f"{field} must use whole UTC seconds")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanError(f"{field} must be a positive integer")
    return value


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise PlanError(f"{field} must be a bounded named declaration")
    return value


def _privacy_check(value: Any, path: str = "input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if any(part in lowered for part in PROHIBITED_KEY_PARTS):
                raise PlanError(f"prohibited privacy field at {path}.{key}")
            _privacy_check(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _privacy_check(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if "token.place?" in lowered or "token.place#" in lowered or "token.place@" in lowered:
            raise PlanError(f"prohibited URL material at {path}")
        if "production" in lowered or "token.place" in lowered and AUTHORITY not in lowered:
            raise PlanError(f"non-staging or ambiguous target material at {path}")


def _routes(
    value: Any, expected: tuple[tuple[str, str, int], ...], where: str
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PlanError(f"{where} must be a list")
    normalized = []
    for index, route in enumerate(value):
        route = _exact(route, ROUTE_FIELDS, f"{where}[{index}]")
        normalized.append((route["method"], route["path"], route["expected_status"]))
    if tuple(normalized) != expected:
        raise PlanError(f"{where} must match the exact ordered route contract")
    return value


def build_plan(input_bytes: bytes, configuration_bytes: bytes) -> dict[str, Any]:
    """Validate local bytes and return a deterministic, privacy-safe plan."""
    try:
        document = json.loads(input_bytes, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError("input must be valid UTF-8 JSON") from exc
    document = _exact(document, TOP_FIELDS, "input")
    _privacy_check(document)
    if document["schema_version"] != SCHEMA_VERSION or isinstance(document["schema_version"], bool):
        raise PlanError("unsupported schema_version")
    if document["lifecycle"] != LIFECYCLE:
        raise PlanError(f"lifecycle must be {LIFECYCLE}")

    target = _exact(document["target"], TARGET_FIELDS, "target")
    if target["scheme"] != "https" or target["authority"] != AUTHORITY:
        raise PlanError("target must be canonical HTTPS staging.token.place")
    if target["follow_redirects"] is not False:
        raise PlanError("redirect following must be disabled")
    _routes(target["emulation_routes"], EMULATION_ROUTES, "target.emulation_routes")
    _routes(target["health_controls"], HEALTH_CONTROLS, "target.health_controls")

    policy = _exact(document["policy"], POLICY_FIELDS, "policy")
    for field in POLICY_FIELDS:
        _positive_int(policy[field], f"policy.{field}")
    if policy["retention_seconds"] > policy["max_retention_seconds"]:
        raise PlanError("retention exceeds its reviewed bound")

    rule = _exact(document["rule_attestation"], RULE_FIELDS, "rule_attestation")
    for field in ("rule_identity_sha256", "reviewed_configuration_sha256"):
        if not isinstance(rule[field], str) or not SHA256.fullmatch(rule[field]):
            raise PlanError(f"rule_attestation.{field} must be lowercase SHA-256")
    actual_config_hash = hashlib.sha256(configuration_bytes).hexdigest()
    if actual_config_hash != rule["reviewed_configuration_sha256"]:
        raise PlanError("reviewed configuration hash does not bind the supplied bytes")
    if rule["reviewer_decision"] != "scope-exactly-approved":
        raise PlanError("reviewer declaration does not approve the exact scope")
    _name(rule["reviewer"], "rule_attestation.reviewer")
    if rule["scope_authority"] != AUTHORITY or rule["scope_methods"] != ["GET"]:
        raise PlanError("attested rule authority and method scope must be exact")
    if rule["scope_paths"] != ["/", "/api/v1/meta"]:
        raise PlanError("attested rule path scope must be exact and exclude health controls")

    auth = _exact(document["authorization"], AUTH_FIELDS, "authorization")
    for field in ("authorizer", "removal_owner", "handoff", "escalation"):
        _name(auth[field], f"authorization.{field}")
    times = {
        field: _timestamp(
            (
                document["created_at"]
                if field == "created_at"
                else rule[field] if field == "attested_at" else auth[field]
            ),
            field,
        )
        for field in (
            "created_at",
            "attested_at",
            "authorized_at",
            "rehearsal_starts_at",
            "rehearsal_ends_at",
            "review_ends_at",
            "expires_at",
            "removal_deadline_at",
        )
    }
    now = times["created_at"]
    skew = policy["max_future_skew_seconds"]
    age = policy["max_evidence_age_seconds"]
    for field in ("attested_at", "authorized_at"):
        delta = (now - times[field]).total_seconds()
        if delta > age or delta < -skew:
            raise PlanError(f"{field} is stale or future-dated")
    if not (times["rehearsal_starts_at"] >= now >= times["authorized_at"]):
        raise PlanError("rehearsal start or authorization chronology is inconsistent")
    if not (times["rehearsal_starts_at"] < times["rehearsal_ends_at"] <= times["expires_at"]):
        raise PlanError("rehearsal window or expiry is inconsistent")
    if not (times["rehearsal_ends_at"] <= times["review_ends_at"] <= times["expires_at"]):
        raise PlanError("review window or expiry is inconsistent")
    if not (times["rehearsal_starts_at"] <= times["removal_deadline_at"] <= times["expires_at"]):
        raise PlanError("removal deadline is outside the authorized time box")
    if (times["rehearsal_ends_at"] - times["rehearsal_starts_at"]).total_seconds() > policy[
        "max_rehearsal_seconds"
    ]:
        raise PlanError("rehearsal window exceeds its reviewed bound")
    if (times["review_ends_at"] - times["rehearsal_ends_at"]).total_seconds() > policy[
        "max_review_seconds"
    ]:
        raise PlanError("review window exceeds its reviewed bound")

    return {
        "schema_version": SCHEMA_VERSION,
        "plan_kind": "offline-static-429-boundary-emulation",
        "lifecycle": LIFECYCLE,
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "configuration_sha256": actual_config_hash,
        "created_at": document["created_at"],
        "target": target,
        "rule_attestation": rule,
        "authorization": auth,
        "policy": policy,
        "claims_are_declarations": True,
        "cryptographic_verification_performed": False,
        "capabilities": {"network": False, "mutation": False, "quota_stimulus": False},
    }


def write_plan(path: Path, plan: dict[str, Any]) -> None:
    payload = (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PlanError(f"refusing to overwrite existing plan: {path}") from exc
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reviewed-configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.input.read_bytes(), args.reviewed_configuration.read_bytes())
        write_plan(args.output, plan)
    except (OSError, PlanError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
