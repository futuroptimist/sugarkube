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

SCHEMA_VERSION = 1
AUTHORITY = "staging.token.place"
ROUTES = (
    {"method": "GET", "path": "/", "role": "emulation", "expected_status": 429},
    {"method": "GET", "path": "/api/v1/meta", "role": "emulation", "expected_status": 429},
    {"method": "GET", "path": "/livez", "role": "health-control", "expected_status": 200},
    {"method": "GET", "path": "/healthz", "role": "health-control", "expected_status": 200},
)
TOP_KEYS = {
    "schema_version",
    "lifecycle",
    "target",
    "authorization",
    "rule_scope_attestation",
    "policy",
}
TARGET_KEYS = {"scheme", "authority", "routes", "redirect_policy"}
AUTH_KEYS = {
    "reviewer",
    "decision",
    "decided_at",
    "rehearsal_start",
    "rehearsal_end",
    "review_start",
    "review_end",
    "expires_at",
    "removal_deadline",
    "removal_owner",
    "handoff",
    "escalation",
}
ATTEST_KEYS = {
    "reviewer",
    "decision",
    "attested_at",
    "authority",
    "methods",
    "emulated_paths",
    "rule_identity_sha256",
    "reviewed_configuration_sha256",
}
POLICY_KEYS = {
    "validation_time",
    "freshness_seconds",
    "retention_seconds",
    "timeout_seconds",
}
PROHIBITED_KEY = re.compile(
    r"(?:token|credential|cookie|body|request.?id|caller.?id|raw|expression|query|private.?url|"
    r"header|prompt|response|ciphertext|error)",
    re.IGNORECASE,
)
SHA256 = re.compile(r"[0-9a-f]{64}")


class PlanError(ValueError):
    """An input failed closed validation."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"duplicate field: {key}")
        result[key] = value
    return result


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    missing, unknown = expected - value.keys(), value.keys() - expected
    if missing or unknown:
        raise PlanError(
            f"invalid {label} fields; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PlanError(f"{label} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PlanError(f"{label} is malformed") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise PlanError(f"{label} must be second-precision UTC")
    return parsed


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PlanError(f"{label} must be a non-empty trimmed string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:  # bool is intentionally rejected
        raise PlanError(f"{label} must be a positive integer")
    return value


def _reject_private_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if PROHIBITED_KEY.search(key):
                raise PlanError(f"prohibited privacy field: {key}")
            _reject_private_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private_fields(nested)


def parse_and_validate(raw: bytes) -> dict[str, Any]:
    """Parse strict JSON and return a deterministic, privacy-safe plan."""
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError("input must be UTF-8 JSON") from exc
    _reject_private_fields(data)
    root = _exact_keys(data, TOP_KEYS, "input")
    if root["schema_version"] != SCHEMA_VERSION:
        raise PlanError("unsupported schema_version")
    if root["lifecycle"] != "authorized-static-emulation":
        raise PlanError("explicit authorized-static-emulation lifecycle is required")

    target = _exact_keys(root["target"], TARGET_KEYS, "target")
    if target != {
        "scheme": "https",
        "authority": AUTHORITY,
        "routes": list(ROUTES),
        "redirect_policy": "reject",
    }:
        raise PlanError("target must exactly match the canonical static-emulation route contract")

    auth = _exact_keys(root["authorization"], AUTH_KEYS, "authorization")
    attest = _exact_keys(root["rule_scope_attestation"], ATTEST_KEYS, "rule_scope_attestation")
    policy = _exact_keys(root["policy"], POLICY_KEYS, "policy")
    for key in ("reviewer", "decision", "removal_owner", "handoff", "escalation"):
        _nonempty(auth[key], f"authorization.{key}")
    if auth["decision"] != "approved":
        raise PlanError("authorization decision must be approved")
    for key in ("reviewer", "decision"):
        _nonempty(attest[key], f"rule_scope_attestation.{key}")
    if attest["decision"] != "scope-approved":
        raise PlanError("rule scope decision must be scope-approved")
    if attest["authority"] != AUTHORITY or attest["methods"] != ["GET"]:
        raise PlanError("attested authority and method must be exact")
    if attest["emulated_paths"] != ["/", "/api/v1/meta"]:
        raise PlanError("attested emulation scope must contain exactly the two emulated paths")
    for key in ("rule_identity_sha256", "reviewed_configuration_sha256"):
        if not isinstance(attest[key], str) or not SHA256.fullmatch(attest[key]):
            raise PlanError(f"{key} must be a lowercase SHA-256 digest")

    now = _timestamp(policy["validation_time"], "policy.validation_time")
    freshness = _positive_int(policy["freshness_seconds"], "policy.freshness_seconds")
    _positive_int(policy["retention_seconds"], "policy.retention_seconds")
    _positive_int(policy["timeout_seconds"], "policy.timeout_seconds")
    decided = _timestamp(auth["decided_at"], "authorization.decided_at")
    attested = _timestamp(attest["attested_at"], "rule_scope_attestation.attested_at")
    rehearsal_start = _timestamp(auth["rehearsal_start"], "authorization.rehearsal_start")
    rehearsal_end = _timestamp(auth["rehearsal_end"], "authorization.rehearsal_end")
    review_start = _timestamp(auth["review_start"], "authorization.review_start")
    review_end = _timestamp(auth["review_end"], "authorization.review_end")
    expiry = _timestamp(auth["expires_at"], "authorization.expires_at")
    removal = _timestamp(auth["removal_deadline"], "authorization.removal_deadline")
    if decided > now or attested > now:
        raise PlanError("authorization and attestation evidence cannot be future-dated")
    if (now - decided).total_seconds() > freshness or (now - attested).total_seconds() > freshness:
        raise PlanError("authorization or attestation evidence is stale")
    if not (rehearsal_start <= now < rehearsal_end):
        raise PlanError("validation time must be within the bounded rehearsal window")
    if not (rehearsal_start <= review_start < review_end <= rehearsal_end):
        raise PlanError("review window must be bounded by the rehearsal window")
    if not (now < expiry <= rehearsal_end):
        raise PlanError("authorization expiry must be future and within the rehearsal window")
    if not (now < removal <= rehearsal_end):
        raise PlanError("removal deadline must be future and within the rehearsal window")

    return {
        "schema_version": SCHEMA_VERSION,
        "plan_type": "offline-static-429-emulation",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "lifecycle": root["lifecycle"],
        "target": target,
        "authorization_claim": auth,
        "rule_scope_claim": attest,
        "policy": policy,
        "capabilities": {"network": False, "mutation": False, "quota_stimulus": False},
        "claim_notice": (
            "Declarations and byte hashes provide binding, not authentication or proof."
        ),
    }


def write_exclusive(path: Path, plan: dict[str, Any]) -> None:
    """Create *path* atomically enough to prevent silent replacement."""
    payload = (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = parse_and_validate(args.input.read_bytes())
        write_exclusive(args.output, plan)
    except (OSError, PlanError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
