#!/usr/bin/env python3
"""Build a privacy-safe static-429 plan from local files only.

This module intentionally contains no observer, network client, process execution, or
cleanup implementation.  Attestations are declarations, not authenticated proofs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LIFECYCLE = "authorized-static-emulation"
AUTHORITY = "staging.token.place"
EMULATION_ROUTES = ("/", "/api/v1/meta")
HEALTH_ROUTES = ("/livez", "/healthz")
ROUTES = EMULATION_ROUTES + HEALTH_ROUTES
SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")

ROOT_FIELDS = {"schemaVersion", "target", "authorization", "ruleAttestation", "policy"}
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
}
ATTESTATION_FIELDS = {
    "reviewer",
    "decision",
    "declaredAt",
    "rulePreExisting",
    "ruleIdentitySha256",
    "reviewedConfigurationSha256",
    "scheme",
    "authority",
    "method",
    "emulationPaths",
    "healthControlPaths",
    "followRedirects",
}
POLICY_FIELDS = {
    "maxEvidenceAgeSeconds",
    "maxFutureSkewSeconds",
    "maxRehearsalWindowSeconds",
    "maxReviewWindowSeconds",
    "timeoutSeconds",
    "retentionSeconds",
}
POLICY_MAXIMUMS = {
    "maxEvidenceAgeSeconds": 86_400,
    "maxFutureSkewSeconds": 300,
    "maxRehearsalWindowSeconds": 3_600,
    "maxReviewWindowSeconds": 86_400,
    "timeoutSeconds": 60,
    "retentionSeconds": 2_592_000,
}
PROHIBITED_KEYS = {
    "token",
    "tokens",
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "responsebody",
    "body",
    "callerid",
    "requestid",
    "identifier",
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


class PlanError(ValueError):
    """The local planning input fails closed."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"duplicate field: {key}")
        result[key] = value
    return result


def load_input_bytes(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanError("input must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PlanError("input must be an object")
    return value


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise PlanError(f"{label} schema mismatch")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PlanError(f"{label} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PlanError(f"malformed {label}") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise PlanError(f"{label} must use whole UTC seconds")
    canonical = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    if value != canonical:
        raise PlanError(f"{label} is not canonical")
    return parsed


def _safe_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 200
    ):
        raise PlanError(f"{label} must be a short named value")
    if any(character in value for character in ("\n", "\r", "?", "#", "@")) or "://" in value:
        raise PlanError(f"{label} contains prohibited data")
    return value


def _privacy_check(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if normalized in PROHIBITED_KEYS:
                raise PlanError(f"prohibited privacy field: {key}")
            _privacy_check(child)
    elif isinstance(value, list):
        for child in value:
            _privacy_check(child)


def _validate_scope(value: dict[str, Any], label: str) -> None:
    if value["scheme"] != "https" or value["authority"] != AUTHORITY or value["method"] != "GET":
        raise PlanError(f"{label} is not the canonical staging HTTPS target")
    if value["emulationPaths"] != list(EMULATION_ROUTES):
        raise PlanError(f"{label} emulation scope must be exact")
    if value["healthControlPaths"] != list(HEALTH_ROUTES):
        raise PlanError(f"{label} health controls must be exact and independent")
    if value["followRedirects"] is not False:
        raise PlanError(f"{label} must reject redirects")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build_plan(
    raw: bytes, rule_identity: bytes, reviewed_configuration: bytes, *, now: datetime | None = None
) -> dict[str, Any]:
    """Validate exact local bytes and return a deterministic, non-executable plan."""
    value = load_input_bytes(raw)
    _privacy_check(value)
    _exact(value, ROOT_FIELDS, "input")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != SCHEMA_VERSION:
        raise PlanError("unsupported schemaVersion")

    target = _exact(value["target"], TARGET_FIELDS, "target")
    authorization = _exact(value["authorization"], AUTH_FIELDS, "authorization")
    attestation = _exact(value["ruleAttestation"], ATTESTATION_FIELDS, "ruleAttestation")
    policy = _exact(value["policy"], POLICY_FIELDS, "policy")
    _validate_scope(target, "target")
    _validate_scope(attestation, "rule attestation")
    if authorization["lifecycle"] != LIFECYCLE:
        raise PlanError("explicit authorized-static-emulation lifecycle is required")
    if attestation["decision"] != "approved" or attestation["rulePreExisting"] is not True:
        raise PlanError("reviewer must declare the exact pre-existing rule approved")
    for field in ("reviewer", "removalOwner", "handoff", "escalation"):
        owner = authorization[field] if field != "reviewer" else attestation[field]
        _safe_text(owner, field)
    for field in POLICY_FIELDS:
        if type(policy[field]) is not int or policy[field] <= 0:
            raise PlanError(f"policy {field} must be a positive integer supplied by the caller")
        if policy[field] > POLICY_MAXIMUMS[field]:
            raise PlanError(f"policy {field} exceeds the safety maximum")
    for field in ("ruleIdentitySha256", "reviewedConfigurationSha256"):
        if not isinstance(attestation[field], str) or not SHA256_RE.fullmatch(attestation[field]):
            raise PlanError(f"{field} must be a lowercase SHA-256 digest")
    if not rule_identity:
        raise PlanError("rule identity bytes must not be empty")
    if not reviewed_configuration:
        raise PlanError("reviewed configuration bytes must not be empty")
    if attestation["ruleIdentitySha256"] != _digest(rule_identity):
        raise PlanError("rule identity bytes do not match the attested hash")
    if attestation["reviewedConfigurationSha256"] != _digest(reviewed_configuration):
        raise PlanError("reviewed configuration bytes do not match the attested hash")

    timestamps = {
        field: _timestamp(authorization[field], field)
        for field in (
            "authorizedAt",
            "expiresAt",
            "rehearsalStartsAt",
            "rehearsalEndsAt",
            "reviewStartsAt",
            "reviewEndsAt",
            "removalDeadline",
        )
    }
    declared = _timestamp(attestation["declaredAt"], "declaredAt")
    current = now or datetime.now(timezone.utc).replace(microsecond=0)
    if current.tzinfo != timezone.utc:
        raise PlanError("validation time must be UTC")
    future_skew = policy["maxFutureSkewSeconds"]
    evidence_age = policy["maxEvidenceAgeSeconds"]
    if (
        declared.timestamp() > current.timestamp() + future_skew
        or timestamps["authorizedAt"].timestamp() > current.timestamp() + future_skew
    ):
        raise PlanError("authorization evidence is future-dated")
    if (current - declared).total_seconds() > evidence_age or (
        current - timestamps["authorizedAt"]
    ).total_seconds() > evidence_age:
        raise PlanError("authorization evidence is stale")
    if not (
        timestamps["authorizedAt"]
        <= timestamps["rehearsalStartsAt"]
        < timestamps["rehearsalEndsAt"]
        <= timestamps["expiresAt"]
    ):
        raise PlanError("rehearsal window is inconsistent with authorization")
    if not (
        timestamps["rehearsalStartsAt"]
        <= timestamps["reviewStartsAt"]
        < timestamps["reviewEndsAt"]
        <= timestamps["expiresAt"]
    ):
        raise PlanError("review window is inconsistent with authorization")
    if not (
        current < timestamps["removalDeadline"]
        and timestamps["rehearsalStartsAt"]
        <= timestamps["removalDeadline"]
        <= timestamps["rehearsalEndsAt"]
    ):
        raise PlanError("removal deadline must be future-dated within the rehearsal window")
    if (timestamps["rehearsalEndsAt"] - timestamps["rehearsalStartsAt"]).total_seconds() > policy[
        "maxRehearsalWindowSeconds"
    ]:
        raise PlanError("rehearsal window exceeds supplied policy")
    if (timestamps["reviewEndsAt"] - timestamps["reviewStartsAt"]).total_seconds() > policy[
        "maxReviewWindowSeconds"
    ]:
        raise PlanError("review window exceeds supplied policy")
    if not (timestamps["rehearsalStartsAt"] <= current < timestamps["expiresAt"]):
        raise PlanError("plan is outside its bounded authorization window")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "planType": "offline-static-429-boundary-emulation",
        "executable": False,
        "networkCapable": False,
        "mutationCapable": False,
        "quotaDrillEvidence": False,
        "inputSha256": _digest(raw),
        "ruleIdentitySha256": attestation["ruleIdentitySha256"],
        "reviewedConfigurationSha256": attestation["reviewedConfigurationSha256"],
        "target": target,
        "expectedStatuses": {path: 429 if path in EMULATION_ROUTES else 200 for path in ROUTES},
        "authorization": authorization,
        "reviewerDeclaration": {
            "reviewer": attestation["reviewer"],
            "decision": attestation["decision"],
            "declaredAt": attestation["declaredAt"],
            "authenticated": False,
            "independentlyProven": False,
        },
        "policy": policy,
    }


def write_exclusive(path: Path, plan: dict[str, Any]) -> None:
    payload = (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PlanError(f"refusing to overwrite existing plan: {path}") from exc
    raw_descriptor = descriptor
    try:
        output = os.fdopen(descriptor, "wb")
        raw_descriptor = -1
        with output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            # Some filesystems do not support directory fsync. The file itself is durable.
            pass
    except BaseException:
        if raw_descriptor >= 0:
            os.close(raw_descriptor)
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--rule-identity", required=True, type=Path)
    parser.add_argument("--reviewed-configuration", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lifecycle", required=True, choices=[LIFECYCLE])
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        value = load_input_bytes(raw)
        authorization = value.get("authorization")
        if not isinstance(authorization, dict) or authorization.get("lifecycle") != args.lifecycle:
            raise PlanError("CLI lifecycle does not match authorization")
        plan = build_plan(
            raw, args.rule_identity.read_bytes(), args.reviewed_configuration.read_bytes()
        )
        write_exclusive(args.output, plan)
    except (OSError, PlanError) as exc:
        print(f"plan refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
