#!/usr/bin/env python3
"""Build an immutable, offline plan for static 429 boundary emulation.

This module deliberately contains no observation or cleanup implementation.  It only
validates a local JSON authorization declaration and writes a privacy-safe plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """The local authorization document is not safe to plan."""


SCHEMA_VERSION = 1
LIFECYCLE = "authorized-static-emulation"
AUTHORITY = "staging.token.place"
TARGETS = (
    ("GET", "https://staging.token.place/", 429, "emulation"),
    ("GET", "https://staging.token.place/api/v1/meta", 429, "emulation"),
    ("GET", "https://staging.token.place/livez", 200, "health-control"),
    ("GET", "https://staging.token.place/healthz", 200, "health-control"),
)
ROOT_FIELDS = {
    "schema_version",
    "lifecycle",
    "planned_at",
    "authorization",
    "rule_attestation",
    "policy",
    "targets",
}
AUTH_FIELDS = {
    "evidence_at",
    "expires_at",
    "rehearsal_starts_at",
    "rehearsal_ends_at",
    "review_ends_at",
    "reviewer",
    "reviewer_decision",
    "rule_identity_sha256",
    "removal_owner",
    "handoff",
    "escalation",
}
RULE_FIELDS = {
    "authority",
    "method",
    "paths",
    "rule_identity_sha256",
    "reviewed_configuration_sha256",
    "reviewer",
    "reviewer_decision",
}
POLICY_FIELDS = {
    "freshness_seconds",
    "retention_seconds",
    "timeout_seconds",
    "max_rehearsal_seconds",
    "max_review_seconds",
    "max_authorization_seconds",
}
TARGET_FIELDS = {"method", "url", "expected_status", "role", "follow_redirects"}
PROHIBITED = re.compile(
    r"credential|pass"
    r"word|secret|token|cookie|body|caller|request.?id|query|raw|expression|"
    r"private.?url|header|prompt|response|ciphertext|error",
    re.IGNORECASE,
)
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._@+:/-]{0,127}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"duplicate field: {key}")
        result[key] = value
    return result


def _fields(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    missing, unknown = expected - set(value), set(value) - expected
    if missing or unknown:
        raise PlanError(
            f"{label} fields are not exact (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PlanError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PlanError(f"{label} must be a canonical UTC timestamp") from exc
    return parsed


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanError(f"{label} must be a positive integer")
    return value


def _safe_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value) or PROHIBITED.search(value):
        raise PlanError(f"{label} must be a privacy-safe named declaration")
    return value


def _privacy_check(value: Any, path: str = "input") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if PROHIBITED.search(key):
                raise PlanError(f"prohibited privacy field at {path}")
            _privacy_check(child, f"{path}.{key}")
    elif isinstance(value, list):
        for child in value:
            _privacy_check(child, path)


def load_and_validate(payload: bytes) -> dict[str, Any]:
    """Validate exact local input bytes and return a deterministic plan."""
    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError("input must be UTF-8 JSON") from exc
    _privacy_check(document)
    root = _fields(document, ROOT_FIELDS, "input")
    if root["schema_version"] != SCHEMA_VERSION or isinstance(root["schema_version"], bool):
        raise PlanError("unsupported schema_version")
    if root["lifecycle"] != LIFECYCLE:
        raise PlanError("explicit authorized-static-emulation lifecycle is required")

    policy = _fields(root["policy"], POLICY_FIELDS, "policy")
    freshness = _positive_int(policy["freshness_seconds"], "freshness_seconds")
    _positive_int(policy["retention_seconds"], "retention_seconds")
    _positive_int(policy["timeout_seconds"], "timeout_seconds")
    max_rehearsal = _positive_int(policy["max_rehearsal_seconds"], "max_rehearsal_seconds")
    max_review = _positive_int(policy["max_review_seconds"], "max_review_seconds")
    max_authorization = _positive_int(
        policy["max_authorization_seconds"], "max_authorization_seconds"
    )

    auth = _fields(root["authorization"], AUTH_FIELDS, "authorization")
    planned = _timestamp(root["planned_at"], "planned_at")
    evidence = _timestamp(auth["evidence_at"], "evidence_at")
    expires = _timestamp(auth["expires_at"], "expires_at")
    starts = _timestamp(auth["rehearsal_starts_at"], "rehearsal_starts_at")
    ends = _timestamp(auth["rehearsal_ends_at"], "rehearsal_ends_at")
    review = _timestamp(auth["review_ends_at"], "review_ends_at")
    if evidence > planned or planned - evidence > timedelta(seconds=freshness):
        raise PlanError("authorization evidence is future-dated or stale")
    if not (evidence <= planned <= starts < ends and review >= ends and expires >= review):
        raise PlanError("authorization windows are contradictory or expired")
    if (
        ends - starts > timedelta(seconds=max_rehearsal)
        or review - ends > timedelta(seconds=max_review)
        or expires - evidence > timedelta(seconds=max_authorization)
    ):
        raise PlanError("authorization windows exceed declared policy bounds")
    for field in ("reviewer", "removal_owner", "handoff", "escalation"):
        _safe_name(auth[field], field)
    if auth["reviewer_decision"] != "approved":
        raise PlanError("reviewer decision must declare approved")

    rule = _fields(root["rule_attestation"], RULE_FIELDS, "rule_attestation")
    if rule["authority"] != AUTHORITY or rule["method"] != "GET":
        raise PlanError("rule scope must use the canonical staging authority and GET")
    if rule["paths"] != ["/", "/api/v1/meta"]:
        raise PlanError("rule scope must contain exactly the two emulation paths")
    for field in ("rule_identity_sha256", "reviewed_configuration_sha256"):
        if not isinstance(rule[field], str) or not SHA256.fullmatch(rule[field]):
            raise PlanError(f"{field} must be a lowercase SHA-256 digest")
    if auth["rule_identity_sha256"] != rule["rule_identity_sha256"]:
        raise PlanError("authorization rule identity hash does not match attestation")
    if rule["reviewer"] != auth["reviewer"] or rule["reviewer_decision"] != "approved":
        raise PlanError("rule review declaration does not match authorization")

    targets = root["targets"]
    if not isinstance(targets, list) or len(targets) != len(TARGETS):
        raise PlanError("targets must contain the exact route contract")
    for target, expected in zip(targets, TARGETS):
        item = _fields(target, TARGET_FIELDS, "target")
        actual = (item["method"], item["url"], item["expected_status"], item["role"])
        if actual != expected or item["follow_redirects"] is not False:
            raise PlanError("target is noncanonical or permits redirects")

    return {
        "schema_version": SCHEMA_VERSION,
        "plan_type": "offline-static-429-boundary-emulation",
        "input_sha256": hashlib.sha256(payload).hexdigest(),
        "lifecycle": LIFECYCLE,
        "planned_at": root["planned_at"],
        "authorization": auth,
        "rule_attestation": rule,
        "policy": policy,
        "targets": targets,
        "claims": {
            "reviewer_statements_are_declarations": True,
            "hashes_bind_bytes_but_do_not_prove_truth_or_currency": True,
            "network_observation_authorized": False,
            "quota_exhaustion_evidence": False,
            "rule_mutation_or_cleanup_implemented": False,
        },
    }


def write_plan(plan: dict[str, Any], output: Path) -> None:
    """Create *output* exclusively; never replace an existing plan."""
    encoded = (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(output, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        payload = args.input.read_bytes()
        write_plan(load_and_validate(payload), args.output)
    except (OSError, PlanError) as exc:
        print(f"static-emulation plan refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
