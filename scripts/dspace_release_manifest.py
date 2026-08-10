#!/usr/bin/env python3
"""Validate DSPACE release manifests and record deployment evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

UPSTREAM_FIELDS_V1 = (
    "schemaVersion",
    "app",
    "applicationVersion",
    "sourceRevision",
    "imageTag",
    "imageDigest",
    "chartVersion",
    "chartDigest",
    "semanticTag",
)
UPSTREAM_FIELDS_V2 = UPSTREAM_FIELDS_V1[:4] + ("chartSourceRevision",) + UPSTREAM_FIELDS_V1[4:]
# Retain the public constants for schema-v1 callers and tests.
UPSTREAM_FIELDS = UPSTREAM_FIELDS_V1
CANDIDATE_SUFFIX = (
    "recordType",
    "environment",
    "expectedDefaultChatProvider",
    "approvedAt",
    "approvedBy",
)
FINAL_SUFFIX = (
    "helmRevision",
    "pods",
    "runtimeSourceRevision",
    "runtimeSourceRevisionMethod",
    "verificationResults",
)
CANDIDATE_FIELDS = UPSTREAM_FIELDS_V1 + CANDIDATE_SUFFIX
FINAL_FIELDS = CANDIDATE_FIELDS + FINAL_SUFFIX
OPTIONAL_FINAL_FIELDS = ("runtimeVerification",)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
IMAGE_TAG_RE = re.compile(r"^(?:main|v[0-9]+)-([0-9a-f]{7})$")
PROVIDERS = {"token-place", "openai"}
REVISION_ANNOTATION = "org.opencontainers.image.revision"
RUNTIME_METHOD = "podImageID+ociRevisionAnnotation"
IMAGE_REF = "ghcr.io/democratizedspace/dspace"
CHART_REF = "ghcr.io/democratizedspace/charts/dspace"
RESERVATION_SUFFIX = ".reservation"
FINAL_FIXED_CHECKS = {
    "imageDigest",
    "chartDigest",
    "chartSourceRevision",
    "selectedCoordinates",
    "clusterEnvironment",
    "helmRelease",
    "installedChart",
    "releaseOwnershipAndReadiness",
    "podImageCoordinates",
    "podImageDigests",
}
SCHEMA_V2_FINAL_CHECKS = {"helmStoredValues"}
RUNTIME_VERIFICATION_FIELDS = (
    "schemaVersion",
    "environment",
    "release",
    "namespace",
    "applicationVersion",
    "runtimeSourceRevision",
    "frontendSourceRevision",
    "defaultProvider",
    "journeys",
)
RUNTIME_VERIFICATION_CHECKS = {
    "runtimeIdentity",
    "frontendIdentity",
    "replicaAgreement",
    "publicDirectAgreement",
    "defaultProvider",
    "remoteChatSmoke",
}
PUBLIC_PATH_RE = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")
PLATFORM_CHECK_RE = re.compile(r"^imagePlatformSourceRevision\[(0|[1-9][0-9]*)\]$")
POD_SETTLE_TIMEOUT_SECONDS = 60.0
POD_SETTLE_INTERVAL_SECONDS = 2.0


class ManifestError(ValueError):
    """A release record is missing or inconsistent."""


def helm_status_needs_history(status: object) -> bool:
    """Validate the status revision and report whether chart metadata is absent."""
    if not isinstance(status, dict):
        raise ManifestError("invalid Helm release identity")
    revision = status.get("version")
    if type(revision) is not int or revision < 1:
        raise ManifestError("invalid Helm release identity")
    chart = status.get("chart")
    metadata_missing = "chart" not in status or chart is None
    if isinstance(chart, dict):
        metadata_missing = "metadata" not in chart or chart.get("metadata") is None
    elif not metadata_missing:
        raise ManifestError("invalid Helm release identity")
    return metadata_missing


def resolve_helm_identity(
    status: object,
    history: object,
    expected_name: str,
    expected_version: str,
) -> tuple[str, str, int]:
    """Resolve an exact chart identity, using history only when status omits it."""
    metadata_missing = helm_status_needs_history(status)
    assert isinstance(status, dict)
    revision = status["version"]
    if not metadata_missing:
        metadata = status["chart"]["metadata"]
        if not isinstance(metadata, dict):
            raise ManifestError("invalid Helm release identity")
        name, version = metadata.get("name"), metadata.get("version")
        if name != expected_name or version != expected_version:
            raise ManifestError("invalid Helm release identity")
        return name, version, revision

    if not isinstance(history, list):
        raise ManifestError("invalid Helm release identity")
    matches = []
    for record in history:
        if not isinstance(record, dict):
            raise ManifestError("invalid Helm release identity")
        record_revision = record.get("revision")
        coordinate = record.get("chart")
        if (
            type(record_revision) is not int
            or record_revision < 1
            or not isinstance(coordinate, str)
            or not coordinate
        ):
            raise ManifestError("invalid Helm release identity")
        if record_revision == revision:
            matches.append(record)
    if len(matches) != 1 or matches[0]["chart"] != f"{expected_name}-{expected_version}":
        raise ManifestError("invalid Helm release identity")
    return expected_name, expected_version, revision


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest must be a JSON object")
    return value


def _exact_fields(value: dict[str, Any], expected: tuple[str, ...]) -> None:
    missing = sorted(set(expected) - value.keys())
    unknown = sorted(value.keys() - set(expected))
    if missing or unknown:
        parts = []
        if missing:
            parts.append("missing fields: " + ", ".join(missing))
        if unknown:
            parts.append("unknown fields: " + ", ".join(unknown))
        raise ManifestError("; ".join(parts))


def _upstream_fields(value: dict[str, Any]) -> tuple[str, ...]:
    version = value.get("schemaVersion")
    if type(version) is not int or version not in {1, 2}:
        raise ManifestError("schemaVersion must be integer 1 or 2")
    return UPSTREAM_FIELDS_V1 if version == 1 else UPSTREAM_FIELDS_V2


def candidate_fields(value: dict[str, Any]) -> tuple[str, ...]:
    return _upstream_fields(value) + CANDIDATE_SUFFIX


def _final_fields(value: dict[str, Any]) -> tuple[str, ...]:
    return candidate_fields(value) + FINAL_SUFFIX


def chart_source_revision(value: dict[str, Any]) -> str:
    """Return explicit v2 chart provenance or the schema-v1 same-source invariant."""
    return value["sourceRevision"] if value["schemaVersion"] == 1 else value["chartSourceRevision"]


def required_final_checks(value: dict[str, Any]) -> set[str]:
    """Return the evidence checks required by this record's schema."""
    checks = set(FINAL_FIXED_CHECKS)
    if value["schemaVersion"] == 2:
        checks.update(SCHEMA_V2_FINAL_CHECKS)
    return checks


def _validate_upstream(value: dict[str, Any]) -> None:
    _upstream_fields(value)
    if value["app"] != "dspace":
        raise ManifestError("app must be 'dspace'")
    if not isinstance(value["applicationVersion"], str) or not SEMVER_RE.fullmatch(
        value["applicationVersion"]
    ):
        raise ManifestError("applicationVersion must be strict SemVer")
    sha = value["sourceRevision"]
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise ManifestError("sourceRevision must be a full 40-character lowercase Git SHA")
    chart_sha = chart_source_revision(value)
    if not isinstance(chart_sha, str) or not SHA_RE.fullmatch(chart_sha):
        raise ManifestError("chartSourceRevision must be a full 40-character lowercase Git SHA")
    tag = value["imageTag"]
    match = IMAGE_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        raise ManifestError(
            "imageTag must be an immutable lowercase branch-SHA tag with a seven-character suffix"
        )
    if match.group(1) != sha[:7]:
        raise ManifestError("imageTag suffix does not match sourceRevision")
    for field in ("imageDigest", "chartDigest"):
        if not isinstance(value[field], str) or not DIGEST_RE.fullmatch(value[field]):
            raise ManifestError(f"{field} must be a lowercase sha256 digest")
    if not isinstance(value["chartVersion"], str) or not SEMVER_RE.fullmatch(value["chartVersion"]):
        raise ManifestError("chartVersion must be strict SemVer")
    semantic = value["semanticTag"]
    if not isinstance(semantic, str) or semantic != f"v{value['applicationVersion']}":
        raise ManifestError("semanticTag must equal v<applicationVersion>")


def validate(value: dict[str, Any], finalized: bool | None = None) -> dict[str, Any]:
    record_type = value.get("recordType")
    if finalized is None:
        finalized = record_type == "final"
    expected = _final_fields(value) if finalized else candidate_fields(value)
    if finalized and "runtimeVerification" in value:
        expected += OPTIONAL_FINAL_FIELDS
    _exact_fields(value, expected)
    _validate_upstream(value)
    if record_type != ("final" if finalized else "candidate"):
        raise ManifestError("recordType does not match the requested record kind")
    if value["environment"] not in {"staging", "prod"}:
        raise ManifestError("environment must be staging or prod")
    if value["expectedDefaultChatProvider"] not in PROVIDERS:
        raise ManifestError("expectedDefaultChatProvider must be token-place or openai")
    if not isinstance(value["approvedBy"], str) or not value["approvedBy"].strip():
        raise ManifestError("approvedBy must be non-empty")
    approved = value["approvedAt"]
    if not isinstance(approved, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", approved
    ):
        raise ManifestError("approvedAt must be canonical UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        dt.datetime.strptime(approved, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ManifestError("approvedAt is not a valid UTC timestamp") from exc
    if finalized:
        if (
            not isinstance(value["helmRevision"], int)
            or isinstance(value["helmRevision"], bool)
            or value["helmRevision"] < 1
        ):
            raise ManifestError("helmRevision must be a positive integer")
        pods = value["pods"]
        if not isinstance(pods, list) or not pods:
            raise ManifestError("pods must be a non-empty list")
        names: set[str] = set()
        for pod in pods:
            if not isinstance(pod, dict):
                raise ManifestError("each pod must be an object")
            _exact_fields(pod, ("name", "startTime", "imageID"))
            if not all(isinstance(pod[k], str) and pod[k] for k in pod):
                raise ManifestError("pod evidence values must be non-empty strings")
            if pod["name"] in names:
                raise ManifestError("pod names must be unique")
            names.add(pod["name"])
            if _image_id_digest(pod["imageID"]) != value["imageDigest"]:
                raise ManifestError(
                    f"pod {pod['name']} imageID does not match approved imageDigest"
                )
        if value["runtimeSourceRevision"] != value["sourceRevision"]:
            raise ManifestError("runtimeSourceRevision must match sourceRevision")
        if value["runtimeSourceRevisionMethod"] != RUNTIME_METHOD:
            raise ManifestError(f"runtimeSourceRevisionMethod must be {RUNTIME_METHOD}")
        if "runtimeVerification" in value:
            proof = value["runtimeVerification"]
            if not isinstance(proof, dict) or set(proof) != set(RUNTIME_VERIFICATION_FIELDS):
                raise ManifestError("runtimeVerification has an incompatible verifier schema")
            if type(proof["schemaVersion"]) is not int or proof["schemaVersion"] != 1:
                raise ManifestError("runtimeVerification schemaVersion must be integer 1")
            if any(
                proof[field] != expected_value
                for field, expected_value in {
                    "environment": value["environment"],
                    "release": "dspace",
                    "namespace": "dspace",
                    "applicationVersion": value["applicationVersion"],
                    "runtimeSourceRevision": value["sourceRevision"],
                    "frontendSourceRevision": value["sourceRevision"],
                    "defaultProvider": value["expectedDefaultChatProvider"],
                }.items()
            ):
                raise ManifestError("runtimeVerification does not match approved release")
            journeys = proof["journeys"]
            if not isinstance(journeys, list) or not journeys:
                raise ManifestError("runtimeVerification lacks successful bounded journeys")
            journey_names: set[str] = set()
            for item in journeys:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"name", "passed"}
                    or not isinstance(item["name"], str)
                    or not PUBLIC_PATH_RE.fullmatch(item["name"])
                    or item["name"] in journey_names
                    or item["passed"] is not True
                ):
                    raise ManifestError("runtimeVerification lacks successful bounded journeys")
                journey_names.add(item["name"])
            if "/chat" not in journey_names:
                raise ManifestError("runtimeVerification lacks successful bounded journeys")
        results = value["verificationResults"]
        if not isinstance(results, list) or not results:
            raise ManifestError("verificationResults must be a non-empty list")
        checks: set[str] = set()
        platform_indices: list[int] = []
        for result in results:
            if not isinstance(result, dict):
                raise ManifestError("verification results must be objects")
            _exact_fields(result, ("check", "passed", "details"))
            if (
                not isinstance(result["check"], str)
                or not isinstance(result["passed"], bool)
                or not isinstance(result["details"], str)
                or not result["check"]
                or not result["details"]
            ):
                raise ManifestError("verification result fields have invalid types")
            if not result["passed"]:
                raise ManifestError(f"verification failed: {result['check']}")
            check = result["check"]
            if check in checks:
                raise ManifestError(f"duplicate verification result: {check}")
            checks.add(check)
            platform_match = PLATFORM_CHECK_RE.fullmatch(check)
            if platform_match:
                platform_indices.append(int(platform_match.group(1)))
            elif check not in required_final_checks(value) | RUNTIME_VERIFICATION_CHECKS:
                raise ManifestError(f"unknown verification result: {check}")
        missing = sorted(required_final_checks(value) - checks)
        if missing:
            raise ManifestError("missing verification results: " + ", ".join(missing))
        if "runtimeVerification" in value:
            missing_runtime = sorted(RUNTIME_VERIFICATION_CHECKS - checks)
            if missing_runtime:
                raise ManifestError(
                    "missing runtime verification results: " + ", ".join(missing_runtime)
                )
        elif checks & RUNTIME_VERIFICATION_CHECKS:
            raise ManifestError("runtime verification results require runtimeVerification proof")
        if sorted(platform_indices) != list(range(len(platform_indices))):
            raise ManifestError("image platform verification indices must be contiguous from zero")
        if not platform_indices:
            raise ManifestError("at least one image platform verification result is required")
    return value


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ManifestError(f"refusing to overwrite existing record: {path}") from exc
        _sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        pass


def reservation_path(output: Path) -> Path:
    """Return the non-secret sidecar used to reserve an evidence destination."""
    normalized = output.expanduser().resolve(strict=False)
    return normalized.with_name(normalized.name + RESERVATION_SUFFIX)


def _candidate_fingerprint(value: dict[str, Any]) -> str:
    validate(value, False)
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def reserve(
    output: Path, value: dict[str, Any], environment: str, release: str, namespace: str
) -> str:
    """Atomically reserve output for one invocation and return its opaque ID."""
    validate(value, False)
    if value["environment"] != environment:
        raise ManifestError("reservation environment does not match candidate")
    normalized = output.expanduser().resolve(strict=False)
    sidecar = reservation_path(normalized)
    normalized.parent.mkdir(parents=True, exist_ok=True)
    if normalized.exists():
        raise ManifestError(f"refusing to overwrite existing record: {normalized}")
    identifier = secrets.token_hex(32)
    metadata = {
        "schemaVersion": 1,
        "output": str(normalized),
        "candidateFingerprint": _candidate_fingerprint(value),
        "environment": environment,
        "release": release,
        "namespace": namespace,
        "reservationId": identifier,
    }
    try:
        fd = os.open(sidecar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ManifestError(f"evidence destination is already reserved: {sidecar}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(metadata))
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(normalized.parent)
    except BaseException:
        sidecar.unlink(missing_ok=True)
        raise
    return identifier


def verify_reservation(
    output: Path,
    value: dict[str, Any],
    environment: str,
    release: str,
    namespace: str,
    identifier: str,
) -> Path:
    normalized = output.expanduser().resolve(strict=False)
    sidecar = reservation_path(normalized)
    metadata = _object(sidecar)
    expected = {
        "schemaVersion": 1,
        "output": str(normalized),
        "candidateFingerprint": _candidate_fingerprint(value),
        "environment": environment,
        "release": release,
        "namespace": namespace,
        "reservationId": identifier,
    }
    if not secrets.compare_digest(
        json.dumps(metadata, sort_keys=True), json.dumps(expected, sort_keys=True)
    ):
        raise ManifestError("reservation ownership or deployment coordinates do not match")
    if normalized.exists():
        raise ManifestError(f"refusing to overwrite existing record: {normalized}")
    return sidecar


def candidate(
    upstream: dict[str, Any],
    environment: str,
    provider: str,
    approved_at: str,
    approved_by: str,
) -> dict[str, Any]:
    _exact_fields(upstream, _upstream_fields(upstream))
    _validate_upstream(upstream)
    fields = _upstream_fields(upstream)
    result = {field: upstream[field] for field in fields}
    result.update(
        recordType="candidate",
        environment=environment,
        expectedDefaultChatProvider=provider,
        approvedAt=approved_at,
        approvedBy=approved_by,
    )
    return validate(result, False)


def evidence_path(value: dict[str, Any]) -> Path:
    """Return the stable, approval-unique default evidence destination."""
    validate(value, False)
    approved = value["approvedAt"].replace("-", "").replace(":", "")
    return (
        Path("deployment-evidence")
        / "dspace"
        / value["environment"]
        / (f"{value['imageTag']}-{approved}.json")
    )


def _run(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise ManifestError(
            f"command failed ({command[0]}): {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout


def _json_run(runner, command: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(runner(command))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid JSON returned by {command[0]}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{command[0]} returned a non-object JSON value")
    return value


def _revision(config: dict[str, Any]) -> str | None:
    labels = config.get("config", {}).get("Labels", {})
    annotations = config.get("annotations", {})
    return labels.get(REVISION_ANNOTATION) or annotations.get(REVISION_ANNOTATION)


def _descriptor(oras: str, tagged_ref: str, runner) -> str:
    value = _json_run(runner, [oras, "manifest", "fetch", "--descriptor", tagged_ref])
    digest = value.get("digest")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise ManifestError(f"OCI descriptor for {tagged_ref} lacks a canonical digest")
    return digest


def _image_evidence(oras: str, repository: str, tag: str, runner) -> tuple[str, list[str]]:
    digest = _descriptor(oras, f"{repository}:{tag}", runner)
    index = _json_run(runner, [oras, "manifest", "fetch", f"{repository}@{digest}"])
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or not manifests:
        raise ManifestError("image artifact must be an OCI image index with platform manifests")
    revisions = []
    for platform in manifests:
        platform_digest = platform.get("digest") if isinstance(platform, dict) else None
        if not isinstance(platform_digest, str) or not DIGEST_RE.fullmatch(platform_digest):
            raise ManifestError("image index contains a non-canonical platform digest")
        image_manifest = _json_run(
            runner, [oras, "manifest", "fetch", f"{repository}@{platform_digest}"]
        )
        config_digest = image_manifest.get("config", {}).get("digest")
        if not isinstance(config_digest, str) or not DIGEST_RE.fullmatch(config_digest):
            raise ManifestError("image manifest lacks a canonical config digest")
        config = _json_run(
            runner, [oras, "blob", "fetch", "--output", "-", f"{repository}@{config_digest}"]
        )
        revision = _revision(config)
        if not isinstance(revision, str):
            raise ManifestError("image config lacks OCI revision label")
        revisions.append(revision)
    return digest, revisions


def _chart_evidence(oras: str, repository: str, version: str, runner) -> tuple[str, str]:
    digest = _descriptor(oras, f"{repository}:{version}", runner)
    artifact = _json_run(runner, [oras, "manifest", "fetch", f"{repository}@{digest}"])
    config_digest = artifact.get("config", {}).get("digest")
    if not isinstance(config_digest, str) or not DIGEST_RE.fullmatch(config_digest):
        raise ManifestError("chart artifact lacks a canonical config digest")
    config = _json_run(
        runner, [oras, "blob", "fetch", "--output", "-", f"{repository}@{config_digest}"]
    )
    revision = _revision(config)
    if not isinstance(revision, str):
        raise ManifestError("chart config lacks OCI revision metadata")
    return digest, revision


def preflight(
    value: dict[str, Any],
    image_ref: str,
    chart_ref: str,
    oras: str,
    environment: str | None = None,
    image_tag: str | None = None,
    chart_version: str | None = None,
    runner=_run,
) -> list[dict[str, Any]]:
    validate(value, False)
    selected = (
        ("environment", environment),
        ("imageTag", image_tag),
        ("chartVersion", chart_version),
    )
    for field, expected in selected:
        if expected is not None and value[field] != expected:
            raise ManifestError(f"selected {field} does not match approved manifest")
    image_ref = image_ref.removeprefix("oci://")
    chart_ref = chart_ref.removeprefix("oci://")
    if image_ref != IMAGE_REF:
        raise ManifestError(f"image reference must be {IMAGE_REF}")
    if chart_ref != CHART_REF:
        raise ManifestError(f"chart reference must be oci://{CHART_REF}")
    image_digest, image_revisions = _image_evidence(oras, image_ref, value["imageTag"], runner)
    chart_digest, chart_revision = _chart_evidence(oras, chart_ref, value["chartVersion"], runner)
    checks = (
        ("imageDigest", image_digest, value["imageDigest"]),
        ("chartDigest", chart_digest, value["chartDigest"]),
        ("chartSourceRevision", chart_revision, chart_source_revision(value)),
    )
    results = [
        {
            "check": name,
            "passed": actual == expected,
            "details": f"expected {expected}; resolved {actual}",
        }
        for name, actual, expected in checks
    ]
    results.extend(
        {
            "check": f"imagePlatformSourceRevision[{index}]",
            "passed": revision == value["sourceRevision"],
            "details": f"expected {value['sourceRevision']}; resolved {revision}",
        }
        for index, revision in enumerate(image_revisions)
    )
    failed = [item["check"] for item in results if not item["passed"]]
    if failed:
        raise ManifestError("OCI preflight mismatch: " + ", ".join(failed))
    return results


def chart_coordinate(value: dict[str, Any]) -> str:
    """Return the immutable Helm coordinate approved by a validated candidate."""
    validate(value, False)
    return f"oci://{CHART_REF}@{value['chartDigest']}"


def _image_id_digest(image_id: str) -> str:
    match = re.search(r"sha256:[0-9a-f]{64}$", image_id)
    if not match:
        raise ManifestError(f"non-canonical pod imageID: {image_id}")
    return match.group(0)


def _settle_release_pods(
    command: list[str],
    *,
    runner: Any = None,
    monotonic: Any = None,
    sleeper: Any = None,
) -> dict[str, Any]:
    """Wait boundedly for release pods undergoing graceful deletion to disappear."""
    runner = _run if runner is None else runner
    monotonic = time.monotonic if monotonic is None else monotonic
    sleeper = time.sleep if sleeper is None else sleeper
    deadline = monotonic() + POD_SETTLE_TIMEOUT_SECONDS
    while True:
        pods = json.loads(runner(command))
        terminating = [
            item
            for item in pods.get("items", [])
            if isinstance(item, dict)
            and item.get("metadata", {}).get("deletionTimestamp") is not None
        ]
        if not terminating:
            return pods
        if monotonic() >= deadline:
            raise ManifestError("timed out waiting for terminating release pods")
        sleeper(POD_SETTLE_INTERVAL_SECONDS)


def finalize(
    value: dict[str, Any],
    helm_json: dict[str, Any],
    pods_json: dict[str, Any],
    workloads_json: dict[str, Any],
    preflight_results: list[dict[str, Any]],
    *,
    environment: str,
    image_tag: str,
    chart_version: str,
    release: str,
    namespace: str,
    cluster_environment: str,
    invocation_description: str,
    expected_image_coordinate: str | None = None,
    runtime_verification: dict[str, Any] | None = None,
    helm_stored_values_result: dict[str, Any] | None = None,
    helm_history: object = None,
) -> dict[str, Any]:
    validate(value, False)
    selected = {
        "environment": environment,
        "imageTag": image_tag,
        "chartVersion": chart_version,
    }
    for field, actual in selected.items():
        if value[field] != actual:
            raise ManifestError(f"selected {field} does not match approved manifest")
    if cluster_environment != environment:
        raise ManifestError("connected cluster environment does not match selected environment")

    if helm_json.get("name") != release or helm_json.get("namespace") != namespace:
        raise ManifestError("Helm status does not match selected release and namespace")
    helm_info = helm_json.get("info", {})
    if helm_info.get("status") != "deployed":
        raise ManifestError("Helm release status must be deployed")
    if helm_info.get("description") != invocation_description:
        raise ManifestError("Helm release description does not match this invocation")
    try:
        _, _, revision = resolve_helm_identity(helm_json, helm_history, "dspace", chart_version)
    except ManifestError as exc:
        raise ManifestError(
            "installed Helm chart identity or version does not match approval"
        ) from exc

    selector_labels = {
        "app.kubernetes.io/name": "dspace",
        "app.kubernetes.io/instance": release,
    }
    workloads: dict[tuple[str, str], dict[str, Any]] = {}
    for item in workloads_json.get("items", []):
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        kind = item.get("kind") if isinstance(item, dict) else None
        name = metadata.get("name")
        if kind not in {"ReplicaSet", "Deployment"} or not isinstance(name, str):
            raise ManifestError("release workload discovery returned an unexpected object")
        if any(
            metadata.get("labels", {}).get(key) != expected
            for key, expected in selector_labels.items()
        ):
            raise ManifestError("release workload labels do not match selected release")
        if kind == "Deployment":
            annotations = metadata.get("annotations", {})
            if (
                metadata.get("labels", {}).get("app.kubernetes.io/managed-by") != "Helm"
                or annotations.get("meta.helm.sh/release-name") != release
                or annotations.get("meta.helm.sh/release-namespace") != namespace
            ):
                raise ManifestError("Deployment is not owned by the selected Helm release")
        workloads[(kind, name)] = item

    def controller(item: dict[str, Any], expected_kind: str) -> dict[str, Any]:
        references = item.get("metadata", {}).get("ownerReferences", [])
        owners = [
            ref for ref in references if isinstance(ref, dict) and ref.get("controller") is True
        ]
        if len(owners) != 1 or owners[0].get("kind") != expected_kind:
            raise ManifestError(f"broken {expected_kind} controller owner-reference chain")
        owner = workloads.get((expected_kind, owners[0].get("name")))
        if owner is None or owner.get("metadata", {}).get("uid") != owners[0].get("uid"):
            raise ManifestError(f"broken {expected_kind} controller owner-reference chain")
        return owner

    pods = []
    for item in pods_json.get("items", []):
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        if any(
            metadata.get("labels", {}).get(key) != expected
            for key, expected in selector_labels.items()
        ):
            raise ManifestError("pod labels do not match selected release")
        if metadata.get("deletionTimestamp") is not None:
            raise ManifestError("terminating pods cannot provide serving evidence")
        replica_set = controller(item, "ReplicaSet")
        controller(replica_set, "Deployment")
        status = item.get("status", {})
        if status.get("phase") != "Running":
            raise ManifestError("all release pods must be Running")
        conditions = status.get("conditions", [])
        if not any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions):
            raise ManifestError("all release pods must be Ready")
        containers = item.get("spec", {}).get("containers", [])
        application = [container for container in containers if container.get("name") == "dspace"]
        if len(application) != 1:
            raise ManifestError("pod must contain exactly one dspace application container")
        expected_image = expected_image_coordinate or f"{IMAGE_REF}:{image_tag}"
        if application[0].get("image") != expected_image:
            raise ManifestError(
                "pod application image does not match approved repository and imageTag"
            )
        statuses = [
            container
            for container in status.get("containerStatuses", [])
            if container.get("name") == "dspace"
        ]
        if len(statuses) != 1 or statuses[0].get("state", {}).get("running") is None:
            raise ManifestError("dspace application container must be running")
        pods.append(
            {
                "name": metadata.get("name"),
                "startTime": status.get("startTime"),
                "imageID": statuses[0].get("imageID"),
            }
        )
    pods.sort(key=lambda item: str(item["name"]))
    checks = {
        item.get("check")
        for item in preflight_results
        if isinstance(item, dict) and item.get("passed") is True
    }
    required = {"imageDigest", "chartDigest", "chartSourceRevision"}
    if not required <= checks or not any(
        str(check).startswith("imagePlatformSourceRevision[") for check in checks
    ):
        raise ManifestError("finalization requires complete fresh OCI preflight results")
    results = [
        *preflight_results,
        {
            "check": "selectedCoordinates",
            "passed": True,
            "details": f"environment={environment}; imageTag={image_tag}; chartVersion={chart_version}",
        },
        {
            "check": "clusterEnvironment",
            "passed": True,
            "details": f"connected cluster environment={cluster_environment}",
        },
        {
            "check": "helmRelease",
            "passed": True,
            "details": (
                f"release={release}; namespace={namespace}; revision={revision}; "
                "status=deployed; binding=Helm mutation description"
            ),
        },
        {
            "check": "installedChart",
            "passed": True,
            # Helm metadata proves name/version, not immutable OCI content. The
            # guarded mutation therefore installs this approved digest directly.
            "details": (
                f"chart=dspace; version={chart_version}; " f"coordinate={chart_coordinate(value)}"
            ),
        },
        {
            "check": "releaseOwnershipAndReadiness",
            "passed": True,
            "details": f"{len(pods)} pod(s) owned by release workloads and serving",
        },
        {
            "check": "podImageCoordinates",
            "passed": True,
            "details": f"all dspace containers use {IMAGE_REF}:{image_tag}",
        },
        {
            "check": "podImageDigests",
            "passed": True,
            "details": "every running pod imageID matched approved image digest",
        },
    ]
    if value["schemaVersion"] == 2:
        if helm_stored_values_result is None:
            raise ManifestError("schema-v2 finalization requires Helm stored-values verification")
        results.append(helm_stored_values_result)
    if runtime_verification is not None:
        runtime_checks = (
            ("runtimeIdentity", "approved runtime source and image identity verified"),
            ("frontendIdentity", "approved frontend revision marker verified"),
            ("replicaAgreement", "all ready serving replicas agreed"),
            ("publicDirectAgreement", "public and direct build identities agreed"),
            ("defaultProvider", "approved default provider verified"),
            ("remoteChatSmoke", "bounded remote /chat journey passed"),
        )
        results.extend(
            {"check": name, "passed": True, "details": details} for name, details in runtime_checks
        )
    result = dict(value)
    result.update(
        recordType="final",
        helmRevision=revision,
        pods=pods,
        runtimeSourceRevision=value["sourceRevision"],
        runtimeSourceRevisionMethod=RUNTIME_METHOD,
        verificationResults=results,
    )
    if runtime_verification is not None:
        result["runtimeVerification"] = runtime_verification
    return validate(result, True)


def verify_helm_stored_values(
    value: dict[str, Any], stored_values: object, environment: str
) -> dict[str, Any]:
    """Verify selected non-secret Helm values without retaining or reporting the raw values."""
    validate(value, False)
    if not isinstance(stored_values, dict):
        raise ManifestError("Helm stored values must be a JSON object")

    image = stored_values.get("image")
    if not isinstance(image, dict):
        raise ManifestError("Helm stored image values do not match approved coordinates")
    expected = {
        "repository": IMAGE_REF,
        "tag": value["imageTag"],
        "pullPolicy": "Always",
    }
    if any(image.get(field) != expected_value for field, expected_value in expected.items()):
        raise ManifestError("Helm stored image values do not match approved coordinates")

    if environment == "prod":
        metrics = stored_values.get("metrics")
        service_monitor = stored_values.get("serviceMonitor")
        expected_metrics = {
            "enabled": True,
            "auth": {"existingSecret": "dspace-prod-metrics-token", "secretKey": "token"},
        }
        expected_monitor = {
            "enabled": True,
            "interval": "30s",
            "scrapeTimeout": "10s",
            "additionalLabels": {"release": "kube-prometheus-stack"},
            "cluster": "sugarkube-prod",
        }
        if (
            metrics != expected_metrics
            or service_monitor != expected_monitor
            or contains_staging_reference(stored_values)
        ):
            raise ManifestError(
                "Helm stored production metrics values do not match the approved contract"
            )
    return {
        "check": "helmStoredValues",
        "passed": True,
        "details": "stored image coordinates, pull policy, and environment isolation matched approval",
    }


def contains_staging_reference(value: object) -> bool:
    """Detect known staging-only scalar values without reflecting them in diagnostics."""
    forbidden = {"METRICS_TOKEN", "dspace-staging-metrics-token", "sugarkube-int"}
    if isinstance(value, dict):
        return any(
            contains_staging_reference(key) or contains_staging_reference(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_staging_reference(item) for item in value)
    return isinstance(value, str) and value in forbidden


def staging_gate(candidate_value: dict[str, Any], evidence_value: dict[str, Any]) -> int:
    """Validate finalized staging proof and return its recorded Helm revision."""
    validate(candidate_value, False)
    validate(evidence_value, True)
    if candidate_value["environment"] != "prod" or evidence_value["environment"] != "staging":
        raise ManifestError("staging gate requires prod candidate and staging final evidence")
    coordinates = (
        "applicationVersion",
        "sourceRevision",
        "chartSourceRevision",
        "imageTag",
        "imageDigest",
        "chartVersion",
        "chartDigest",
        "semanticTag",
        "expectedDefaultChatProvider",
    )
    if any(
        (
            chart_source_revision(candidate_value)
            if field == "chartSourceRevision"
            else candidate_value[field]
        )
        != (
            chart_source_revision(evidence_value)
            if field == "chartSourceRevision"
            else evidence_value[field]
        )
        for field in coordinates
    ):
        raise ManifestError("manifest/evidence mismatch: staging and prod coordinates differ")
    if "runtimeVerification" not in evidence_value:
        raise ManifestError("staging evidence lacks mandatory runtime verification")
    return evidence_value["helmRevision"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("candidate")
    make.add_argument("--upstream", type=Path, required=True)
    make.add_argument("--output", type=Path, required=True)
    make.add_argument("--environment", required=True)
    make.add_argument("--provider", required=True)
    make.add_argument("--approved-at", required=True)
    make.add_argument("--approved-by", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--final", action="store_true")
    flight = sub.add_parser("preflight")
    flight.add_argument("--manifest", type=Path, required=True)
    flight.add_argument("--image-ref", default=IMAGE_REF)
    flight.add_argument("--chart-ref", default=CHART_REF)
    flight.add_argument("--oras-command", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras"))
    flight.add_argument("--environment")
    flight.add_argument("--image-tag")
    flight.add_argument("--chart-version")
    flight.add_argument("--print-chart-coordinate", action="store_true")
    finish = sub.add_parser("finalize")
    finish.add_argument("--manifest", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument("--environment", required=True)
    finish.add_argument("--image-tag", required=True)
    finish.add_argument("--chart-version", required=True)
    finish.add_argument("--kubeconfig", required=True)
    finish.add_argument("--release", required=True)
    finish.add_argument("--namespace", required=True)
    finish.add_argument("--image-ref", default=IMAGE_REF)
    finish.add_argument("--chart-ref", default=CHART_REF)
    finish.add_argument("--reservation", required=True)
    finish.add_argument("--oras-command", default=os.environ.get("SUGARKUBE_ORAS_COMMAND", "oras"))
    finish.add_argument("--runtime-verification", type=Path)
    gate = sub.add_parser("staging-gate")
    gate.add_argument("--manifest", type=Path, required=True)
    gate.add_argument("--staging-evidence", type=Path, required=True)
    available = sub.add_parser("check-output")
    available.add_argument("--output", type=Path, required=True)
    destination = sub.add_parser("evidence-path")
    destination.add_argument("--manifest", type=Path, required=True)
    claim = sub.add_parser("reserve")
    claim.add_argument("--manifest", type=Path, required=True)
    claim.add_argument("--output", type=Path, required=True)
    claim.add_argument("--environment", required=True)
    claim.add_argument("--release", required=True)
    claim.add_argument("--namespace", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "candidate":
            result = candidate(
                _object(args.upstream),
                args.environment,
                args.provider,
                args.approved_at,
                args.approved_by,
            )
            _write_new(args.output, result)
        elif args.command == "validate":
            result = validate(_object(args.manifest), args.final)
            sys.stdout.write(_canonical(result))
        elif args.command == "preflight":
            source = _object(args.manifest)
            result = preflight(
                source,
                args.image_ref,
                args.chart_ref,
                args.oras_command,
                args.environment,
                args.image_tag,
                args.chart_version,
            )
            if args.print_chart_coordinate:
                sys.stdout.write(chart_coordinate(source) + "\n")
            else:
                sys.stdout.write(_canonical(result))
        elif args.command == "finalize":
            source = _object(args.manifest)
            sidecar = verify_reservation(
                args.output,
                source,
                args.environment,
                args.release,
                args.namespace,
                args.reservation,
            )
            invocation_description = f"sugarkube-release-manifest:{args.reservation}"
            results = preflight(
                source,
                args.image_ref,
                args.chart_ref,
                args.oras_command,
                args.environment,
                args.image_tag,
                args.chart_version,
            )
            cluster_environment = _run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("cluster_identity.py")),
                    "assert",
                    "--kubeconfig",
                    args.kubeconfig,
                    "--env",
                    args.environment,
                ]
            ).strip()
            helm_command = [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "status",
                args.release,
                "--namespace",
                args.namespace,
                "-o",
                "json",
            ]
            history_command = [
                "helm",
                "--kubeconfig",
                args.kubeconfig,
                "history",
                args.release,
                "--namespace",
                args.namespace,
                "-o",
                "json",
            ]

            def helm_snapshot() -> tuple[dict[str, Any], object, tuple[Any, ...]]:
                try:
                    status = json.loads(_run(helm_command))
                except (ManifestError, json.JSONDecodeError) as exc:
                    raise ManifestError("cannot read Helm release identity") from exc
                history = None
                if helm_status_needs_history(status):
                    try:
                        history = json.loads(_run(history_command))
                    except (ManifestError, json.JSONDecodeError) as exc:
                        raise ManifestError("cannot read Helm release identity") from exc
                name, version, revision = resolve_helm_identity(
                    status, history, "dspace", args.chart_version
                )
                info = status.get("info", {})
                if not isinstance(info, dict):
                    raise ManifestError("invalid Helm release identity")
                binding = (
                    status.get("name"),
                    status.get("namespace"),
                    info.get("status"),
                    revision,
                    info.get("description"),
                    name,
                    version,
                )
                return status, history, binding

            helm, helm_history, helm_binding = helm_snapshot()
            stored_values_result = None
            if source["schemaVersion"] == 2:
                stored_values = json.loads(
                    _run(
                        [
                            "helm",
                            "--kubeconfig",
                            args.kubeconfig,
                            "get",
                            "values",
                            args.release,
                            "--namespace",
                            args.namespace,
                            "--all",
                            "-o",
                            "json",
                        ]
                    )
                )
                stored_values_result = verify_helm_stored_values(
                    source, stored_values, args.environment
                )
            pod_command = [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "-n",
                args.namespace,
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}",
                "-o",
                "json",
            ]
            pods = _settle_release_pods(pod_command)
            _, _, settled_binding = helm_snapshot()
            workloads = json.loads(
                _run(
                    [
                        "kubectl",
                        "--kubeconfig",
                        args.kubeconfig,
                        "-n",
                        args.namespace,
                        "get",
                        "replicasets,deployments",
                        "-l",
                        f"app.kubernetes.io/name=dspace,app.kubernetes.io/instance={args.release}",
                        "-o",
                        "json",
                    ]
                )
            )
            result = finalize(
                source,
                helm,
                pods,
                workloads,
                results,
                environment=args.environment,
                image_tag=args.image_tag,
                chart_version=args.chart_version,
                release=args.release,
                namespace=args.namespace,
                cluster_environment=cluster_environment,
                invocation_description=invocation_description,
                runtime_verification=(
                    _object(args.runtime_verification) if args.runtime_verification else None
                ),
                helm_stored_values_result=stored_values_result,
                helm_history=helm_history,
            )
            sidecar = verify_reservation(
                args.output,
                source,
                args.environment,
                args.release,
                args.namespace,
                args.reservation,
            )
            _, _, stable_binding = helm_snapshot()

            if settled_binding != helm_binding or stable_binding != helm_binding:
                raise ManifestError("Helm release changed during evidence collection")
            _write_new(args.output, result)
            sidecar.unlink()
            _sync_directory(args.output.expanduser().resolve(strict=False).parent)
        elif args.command == "staging-gate":
            print(staging_gate(_object(args.manifest), _object(args.staging_evidence)))
        elif args.command == "check-output":
            if args.output.exists():
                raise ManifestError(f"refusing to overwrite existing record: {args.output}")
        elif args.command == "reserve":
            sys.stdout.write(
                reserve(
                    args.output,
                    _object(args.manifest),
                    args.environment,
                    args.release,
                    args.namespace,
                )
                + "\n"
            )
        else:
            sys.stdout.write(str(evidence_path(_object(args.manifest))) + "\n")
    except (ManifestError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
